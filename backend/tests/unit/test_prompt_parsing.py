"""Reading a model's reply, and the resume optimization prompt.

A model's output is not a contract. It arrives fenced, truncated, with fields
missing, with the wrong types, or as an apology in prose -- and every one of
those must produce nothing rather than a half-built suggestion that gets applied
to the wrong part of someone's resume.
"""

from __future__ import annotations

import json

import pytest

from app.integrations.llm.base import CONTEXT_CLOSE, CONTEXT_OPEN
from app.integrations.prompts import resume_optimization
from app.integrations.prompts.parsing import (
    ResponseFormatError,
    parse_suggestions,
)

RESUME = "Worked on the payments backend.\nReduced p99 latency by 35%."
JOB = "We need a backend engineer for payment systems."


def reply(*suggestions: dict) -> str:
    return json.dumps({"suggestions": list(suggestions)})


def a_suggestion(**overrides) -> dict:
    base = {
        "section": "experience",
        "original": "Worked on the payments backend.",
        "suggested": "Built and maintained payment processing services.",
        "rationale": "The job emphasises payment systems.",
        "grounded_in": ["Worked on the payments backend."],
    }
    return {**base, **overrides}


class TestReadingAGoodReply:
    def test_it_reads_the_fields(self) -> None:
        result = parse_suggestions(reply(a_suggestion()))

        assert len(result.suggestions) == 1
        assert result.suggestions[0].original == "Worked on the payments backend."
        assert result.suggestions[0].grounded_in == ("Worked on the payments backend.",)

    def test_an_empty_list_is_a_valid_answer(self) -> None:
        """Distinct from a malformed reply.

        "I have nothing to suggest" is exactly what the prompt asks for when
        every rewrite would require inventing something. Treating it as an error
        would train the wrong reflex into the caller.
        """
        result = parse_suggestions('{"suggestions": []}')

        assert result.suggestions == ()
        assert result.dropped == 0

    @pytest.mark.parametrize(
        "wrapped",
        [
            '```json\n{"suggestions": []}\n```',
            '```\n{"suggestions": []}\n```',
            'Here you go:\n```json\n{"suggestions": []}\n```\nHope that helps!',
        ],
        ids=["json-fence", "bare-fence", "fence-with-prose"],
    )
    def test_markdown_fences_are_tolerated(self, wrapped: str) -> None:
        """Models do this constantly regardless of the instruction. Accepting a
        presentation habit is not leniency about the schema -- what is inside is
        still parsed strictly."""
        assert parse_suggestions(wrapped).suggestions == ()


class TestRejectingABadReply:
    @pytest.mark.parametrize(
        "bad",
        [
            "I'm sorry, I can't help with that.",
            "",
            "null",
            "[]",
            '{"items": []}',
            '{"suggestions": "none"}',
        ],
        ids=["prose", "empty", "null", "array", "wrong-key", "wrong-type"],
    )
    def test_an_unusable_reply_raises(self, bad: str) -> None:
        with pytest.raises(ResponseFormatError):
            parse_suggestions(bad)

    @pytest.mark.parametrize(
        "entry",
        [
            {"suggested": "new text"},
            {"original": "old text"},
            {"original": "", "suggested": "new"},
            {"original": "old", "suggested": "   "},
            {"original": 42, "suggested": "new"},
            "not an object",
        ],
        ids=[
            "no-original",
            "no-suggested",
            "empty-original",
            "blank-suggested",
            "wrong-type",
            "not-object",
        ],
    )
    def test_an_incomplete_entry_is_dropped_not_defaulted(self, entry) -> None:
        """The failure this prevents.

        Defaulting a missing `original` to "" would produce a suggestion that
        matches nothing, or worse, matches everything -- and it would be applied
        to a real resume.
        """
        result = parse_suggestions(reply(entry))

        assert result.suggestions == ()
        assert result.dropped == 1

    def test_one_bad_entry_does_not_discard_the_good_ones(self) -> None:
        """Throwing away valid suggestions because a sibling lost a field is a
        worse answer, not a safer one."""
        result = parse_suggestions(reply(a_suggestion(), {"suggested": "orphan"}))

        assert len(result.suggestions) == 1
        assert result.dropped == 1

    def test_a_rewrite_identical_to_its_source_is_dropped(self) -> None:
        """Offering it asks a reviewer to make a decision with no difference in
        it."""
        same = a_suggestion(suggested="Worked on the payments backend.")

        result = parse_suggestions(reply(same))

        assert result.suggestions == ()
        assert result.dropped == 1

    def test_an_absurdly_long_field_is_dropped(self) -> None:
        """A model echoing its input or writing an essay. Storing it would put an
        unbounded string in a column and in front of a reviewer."""
        result = parse_suggestions(reply(a_suggestion(suggested="x" * 5_000)))

        assert result.suggestions == ()
        assert result.dropped == 1

    def test_more_than_eight_are_capped_and_the_excess_counted(self) -> None:
        result = parse_suggestions(reply(*[a_suggestion() for _ in range(12)]))

        assert len(result.suggestions) == 8
        assert result.dropped == 4

    def test_malformed_grounding_does_not_lose_the_suggestion(self) -> None:
        """`grounded_in` is evidence for a reviewer, not part of the safety
        check -- the validator re-reads the resume itself. So a bad citation
        costs the citation, not the rewrite."""
        result = parse_suggestions(reply(a_suggestion(grounded_in="not a list")))

        assert len(result.suggestions) == 1
        assert result.suggestions[0].grounded_in == ()


class TestTheOptimizationPrompt:
    def test_both_documents_are_untrusted_context(self) -> None:
        """A resume is untrusted, and so is a job description -- it came off
        somebody else's website."""
        rendered = resume_optimization.build(
            resume_text=RESUME, job_title="Backend Engineer", job_description=JOB
        ).render()

        section = rendered.split("[CONTEXT]", 1)[1]
        assert section.count(CONTEXT_OPEN) == 3
        assert section.count(CONTEXT_CLOSE) == 3
        assert RESUME in section
        assert JOB in section

    def test_the_resume_is_not_in_instruction_position(self) -> None:
        rendered = resume_optimization.build(
            resume_text=RESUME, job_title="Backend Engineer", job_description=JOB
        ).render()

        before_context = rendered.split("[CONTEXT]", 1)[0]
        assert RESUME not in before_context

    def test_it_forbids_deriving_a_new_figure(self) -> None:
        """The specific failure the validator catches and the prompt should
        prevent: 900KB to 410KB restated as a percentage that is nowhere in the
        resume."""
        rendered = resume_optimization.build(
            resume_text=RESUME, job_title="X", job_description=JOB
        ).render()

        assert "derive a new figure" in rendered

    def test_it_says_returning_nothing_is_correct(self) -> None:
        """Without this a model pads the list, and padding is invention."""
        rendered = resume_optimization.build(
            resume_text=RESUME, job_title="X", job_description=JOB
        ).render()

        assert "Returning fewer suggestions is always correct" in rendered

    def test_it_is_versioned(self) -> None:
        """An unversioned prompt change is a regression nobody can reproduce."""
        prompt = resume_optimization.build(
            resume_text=RESUME, job_title="X", job_description=JOB
        )

        assert prompt.name == "resume_optimization"
        assert prompt.version
