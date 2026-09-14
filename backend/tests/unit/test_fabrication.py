"""The fabrication validator (ADR-012 step 4).

Two halves, and both matter:

* **It catches inventions.** Every kind of claim an LLM adds to a resume -- a
  metric, a year, a skill, an employer, a certification -- must reject the
  suggestion. A miss here reaches a real resume.
* **It passes honest rewrites.** A validator that rejects everything has perfect
  recall and is useless. The second class pins the rewrites that must survive,
  because those are what the feature exists to produce.
"""

from __future__ import annotations

import pytest

from app.services.resume.fabrication import EntityKind, validate_suggestion
from app.services.resume.skill_extraction import SkillMatcher

#: Named by code point for the same reason the fold table is: written literally,
#: a curly apostrophe in test source is indistinguishable from a typo.
CURLY_APOSTROPHE = chr(0x2019)
NEWLINE = chr(0x000A)

SOURCE = """
Priya Raman
Senior Backend Engineer

Summary
Backend engineer with 6 years building payment services at Zerodha.

Experience
Zerodha - Senior Backend Engineer (March 2019 - Present)
- Worked on the payments backend, handling 12,000 transactions per day.
- Reduced p99 latency by 35% across the settlement service.
- Mentored three junior engineers.

Skills
Python, Django, PostgreSQL, Redis, Docker

Education
B.Tech in Computer Science, NIT Warangal, 2017
"""


def kinds(result) -> set[EntityKind]:
    return {entity.kind for entity in result.fabricated}


def texts(result) -> set[str]:
    return {entity.text.casefold() for entity in result.fabricated}


class TestItCatchesInventions:
    """Each of these is a real thing a model does when asked to "improve" a
    resume. Every one must reject."""

    def test_an_invented_percentage_is_rejected(self) -> None:
        """The canonical case from ADR-012. "improved performance" is a rewrite;
        "improved performance by 40%" is a new claim about the world."""
        result = validate_suggestion(
            suggested="Reduced p99 latency by 40% across the settlement service.",
            source=SOURCE,
        )

        assert result.passed is False
        assert EntityKind.NUMBER in kinds(result)
        assert "40%" in texts(result)

    def test_an_invented_certification_is_rejected(self) -> None:
        """The example ADR-012 opens with, and the most expensive one: it is
        checkable by an interviewer in seconds."""
        result = validate_suggestion(
            suggested="AWS Certified Solutions Architect with payment systems experience.",
            source=SOURCE,
        )

        assert result.passed is False
        assert EntityKind.CREDENTIAL in kinds(result)

    def test_an_invented_employer_is_rejected(self) -> None:
        result = validate_suggestion(
            suggested="Built payment services at Stripe and Zerodha.",
            source=SOURCE,
        )

        assert result.passed is False
        assert "stripe" in texts(result)

    def test_an_invented_year_is_rejected(self) -> None:
        result = validate_suggestion(
            suggested="Led the payments backend since 2015.",
            source=SOURCE,
        )

        assert result.passed is False
        assert EntityKind.DATE in kinds(result)
        assert "2015" in texts(result)

    def test_an_invented_month_is_rejected(self) -> None:
        result = validate_suggestion(
            suggested="Joined Zerodha in January and led the settlement rewrite.",
            source=SOURCE,
        )

        assert result.passed is False
        assert EntityKind.DATE in kinds(result)

    def test_an_invented_skill_is_rejected(self) -> None:
        matcher = SkillMatcher({"Kubernetes": ["kubernetes"], "Docker": ["docker"]})

        result = validate_suggestion(
            suggested="Deployed payment services with Docker and Kubernetes.",
            source=SOURCE,
            matcher=matcher,
        )

        assert result.passed is False
        assert EntityKind.SKILL in kinds(result)
        # Docker is in the source and must not be reported; only Kubernetes is new.
        assert "kubernetes" in texts(result)

    def test_a_headcount_does_not_license_a_percentage(self) -> None:
        """The unit is part of the claim.

        The source says "three junior engineers". Matching on the bare number
        would let a rewrite turn a headcount into "3% growth" -- a different
        assertion sharing a digit.
        """
        result = validate_suggestion(
            suggested="Drove 3% growth in settlement throughput.",
            source=SOURCE,
        )

        assert result.passed is False
        assert "3%" in texts(result)

    def test_a_bigger_version_of_a_real_number_is_rejected(self) -> None:
        """Inflation is the subtle case: 12,000 is real, 120,000 is not, and the
        digits overlap."""
        result = validate_suggestion(
            suggested="Handled 120,000 transactions per day.",
            source=SOURCE,
        )

        assert result.passed is False
        assert EntityKind.NUMBER in kinds(result)

    def test_a_near_miss_skill_name_does_not_pass_on_a_substring(self) -> None:
        """ "Java" must not be satisfied by a source that says "JavaScript"."""
        result = validate_suggestion(
            suggested="Built services in Java.",
            source="Skills: JavaScript, React",
        )

        assert result.passed is False
        assert "java" in texts(result)

    def test_an_invented_employer_is_caught_even_starting_a_sentence(self) -> None:
        """A hole found while building this, and the reason `_SENTENCE_OPENERS`
        exists.

        The first version skipped every sentence-initial capital, on the
        reasoning that the capital says nothing about the word. True -- but it
        meant a fabricated employer became invisible purely by landing first in
        the sentence, which is the single claim this module exists to stop.
        """
        result = validate_suggestion(
            suggested="Stripe was where I built the payments platform.",
            source=SOURCE,
        )

        assert result.passed is False
        assert "stripe" in texts(result)

    def test_a_trailing_full_stop_does_not_hide_an_invention(self) -> None:
        """"Stripe." must be recognised as "Stripe". Keeping the punctuation made
        the token match nothing in the source *and* nothing in the report, so it
        was reported under a name no test could assert on."""
        result = validate_suggestion(suggested="Previously at Stripe.", source=SOURCE)

        assert "stripe" in texts(result)

    def test_every_invention_is_reported_not_just_the_first(self) -> None:
        """The user sees why a suggestion was withheld, so a partial list would
        misrepresent it."""
        result = validate_suggestion(
            suggested="AWS Certified architect at Stripe since 2015, improving latency by 40%.",
            source=SOURCE,
        )

        assert result.passed is False
        assert len(result.fabricated) >= 4

    def test_a_rejection_says_what_was_invented(self) -> None:
        result = validate_suggestion(suggested="Improved latency by 40%.", source=SOURCE)

        reason = result.fabricated[0].reason
        assert "40%" in reason
        assert reason.endswith(".")


class TestItPassesHonestRewrites:
    """A validator that rejects everything has perfect recall and no value.

    These are the rewrites the feature exists to produce, and each one is a false
    positive waiting to happen.
    """

    def test_a_pure_rephrase_passes(self) -> None:
        result = validate_suggestion(
            suggested="Built and maintained payment processing services.",
            source=SOURCE,
        )

        assert result.passed is True
        assert result.fabricated == ()

    def test_a_qualitative_claim_passes(self) -> None:
        """ "improved performance" is allowed precisely because it quantifies
        nothing -- there is no new fact in it."""
        result = validate_suggestion(
            suggested="Improved settlement service performance substantially.",
            source=SOURCE,
        )

        assert result.passed is True

    def test_a_number_already_in_the_resume_passes(self) -> None:
        result = validate_suggestion(
            suggested="Cut p99 latency 35% on the settlement path.",
            source=SOURCE,
        )

        assert result.passed is True

    def test_restating_a_real_employer_passes(self) -> None:
        result = validate_suggestion(
            suggested="Senior Backend Engineer at Zerodha on the payments platform.",
            source=SOURCE,
        )

        assert result.passed is True

    def test_a_possessive_matches_the_plain_name(self) -> None:
        """ "Zerodha's" and "Zerodha" are one organisation. Rejecting on the
        apostrophe would be a false positive with no safety value."""
        result = validate_suggestion(
            suggested="Owned Zerodha's settlement service.",
            source=SOURCE,
        )

        assert result.passed is True

    def test_a_written_number_matches_its_digits(self) -> None:
        """The source says "three junior engineers"; writing it as 3 is a
        notation change, not a claim."""
        result = validate_suggestion(
            suggested="Mentored 3 junior engineers.",
            source=SOURCE,
        )

        assert result.passed is True

    def test_a_sentence_initial_capital_is_not_an_organisation(self) -> None:
        """Otherwise the first word of every suggestion is a fabricated org."""
        result = validate_suggestion(
            suggested="Delivered the payments backend.",
            source=SOURCE,
        )

        assert result.passed is True

    def test_curly_quotes_from_a_word_processor_still_match(self) -> None:
        """A resume pasted out of Word has typographic punctuation and a model's
        output has ASCII. Failing to fold them would reject honest rewrites for a
        reason no user could ever diagnose."""
        result = validate_suggestion(
            suggested="Owned Zerodha's settlement service.",
            source=f"Experience{NEWLINE}Owned Zerodha{CURLY_APOSTROPHE}s settlement service.",
        )

        assert result.passed is True

    def test_a_scale_word_matches_its_abbreviation(self) -> None:
        result = validate_suggestion(
            suggested="Processed $2M in daily volume.",
            source="Processed $2 million in daily volume.",
        )

        assert result.passed is True

    def test_a_skill_already_held_is_not_reported(self) -> None:
        matcher = SkillMatcher({"Docker": ["docker"], "Python": ["python"]})

        result = validate_suggestion(
            suggested="Containerised Python services with Docker.",
            source=SOURCE,
            matcher=matcher,
        )

        assert result.passed is True


class TestEdges:
    def test_an_empty_suggestion_invents_nothing(self) -> None:
        assert validate_suggestion(suggested="", source=SOURCE).passed is True

    def test_an_empty_source_rejects_any_specific_claim(self) -> None:
        """Nothing is grounded, so nothing specific can be asserted."""
        result = validate_suggestion(suggested="Led 4 engineers at Stripe.", source="")

        assert result.passed is False

    def test_the_same_invention_twice_is_reported_once(self) -> None:
        """A list repeating one entity reads as several problems."""
        result = validate_suggestion(
            suggested="Worked at Stripe. Stripe was where I built payments.",
            source=SOURCE,
        )

        assert len([e for e in result.fabricated if e.text.casefold() == "stripe"]) == 1

    @pytest.mark.parametrize(
        "suggested",
        [
            "Improved latency by 40 percent.",
            "Improved latency by 40%.",
            "Achieved a 40x speedup.",
            "Saved $40,000 annually.",
        ],
    )
    def test_units_are_not_interchangeable(self, suggested: str) -> None:
        """40 appears in none of these forms in the source. Each is its own
        claim and each must reject on its own."""
        assert validate_suggestion(suggested=suggested, source=SOURCE).passed is False

    def test_an_unrecognised_opening_verb_over_rejects(self) -> None:
        """The cost of closing the sentence-initial hole, pinned deliberately.

        Checking sentence-initial capitals means an ordinary verb missing from
        `_SENTENCE_OPENERS` is read as an organisation and the suggestion is
        withheld. That is the intended direction -- ADR-012 takes a lost
        suggestion over an admitted fabrication every time -- but it is a real
        cost, and it should fail loudly here if anyone reverses the tradeoff
        without saying so.

        The fix for a specific word is to add it to the list, not to stop
        checking the position.
        """
        result = validate_suggestion(
            suggested="Flibbertigibbeted the payments backend.",
            source=SOURCE,
        )

        assert result.passed is False

    def test_it_never_calls_anything(self) -> None:
        """Purity is the property that makes this testable and auditable.

        A validator that reached for a model would share the failure mode it
        exists to catch, so this pins that the module imports nothing that could.
        """
        import app.services.resume.fabrication as module

        assert not hasattr(module, "httpx")
        assert not hasattr(module, "AsyncSession")
