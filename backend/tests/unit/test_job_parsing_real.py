"""Section parsing against postings shaped like real ones.

**This file exists because its absence was the defect.** `test_job_parsing.py`
covers the mechanism with two bullet cases, both short synthetic strings using
`-` and `*`, and the only posting-shaped fixture in the repo is deliberately
written to parse cleanly. So the happy path was the only path the suite had ever
seen — and 132 of 292 live postings produced no sections at all without a single
test going red.

Every fixture below is modelled on a posting from the live corpus that the parser
failed on before the Phase 6 quality pass, reduced to the shape that caused the
failure. The comments name the shape rather than the employer.
"""

from __future__ import annotations

from app.services.job.normalization import clean_description
from app.services.job.sections import (
    JobSectionType,
    classify_heading,
    detect_sections,
    extract_bullets,
    section_map,
)


def sections_of(description: str) -> dict[JobSectionType, str]:
    """Parse the way the pipeline does — cleaned first, then split."""
    return section_map(detect_sections(clean_description(description)))


def arrays_of(description: str) -> tuple[list[str], list[str]]:
    by_type = sections_of(description)
    return (
        extract_bullets(by_type.get(JobSectionType.RESPONSIBILITIES, "")),
        extract_bullets(by_type.get(JobSectionType.REQUIREMENTS, "")),
    )


class TestHeadingsRealPostingsUse:
    """Phrasings mined from the postings that produced nothing.

    Several are Naukri and Indian-portal conventions, which is why the gap was
    this wide on a corpus of Indian postings — the original vocabulary was
    written from US-style job ads.
    """

    def test_ampersand_forms_of_responsibilities(self):
        """"Role & Responsibilities" was the single commonest missing heading.

        `classify_heading` turns "&" into a space and collapses, so the folded
        form is "role responsibilities" — which matched nothing, because the
        vocabulary only held the "and" spelling.
        """
        assert classify_heading("Role & Responsibilities") is JobSectionType.RESPONSIBILITIES
        assert classify_heading("Roles & Responsibilities") is JobSectionType.RESPONSIBILITIES

    def test_overview_and_summary_forms(self):
        for heading in ("Role Overview", "About the Role", "Job Summary", "What is the role?"):
            assert classify_heading(heading) is JobSectionType.RESPONSIBILITIES, heading

    def test_indian_portal_requirement_forms(self):
        for heading in (
            "Job Requirements",
            "Skills Required",
            "Mandatory Skills",
            "Key Skills",
            "Desired Candidate Profile",
        ):
            assert classify_heading(heading) is JobSectionType.REQUIREMENTS, heading

    def test_what_you_bring_forms(self):
        for heading in ("What You Bring", "What you'll bring", "About You"):
            assert classify_heading(heading) is JobSectionType.REQUIREMENTS, heading

    def test_preferred_candidate_profile_is_nice_to_have_not_required(self):
        """Longest-match matters here.

        "candidate profile" is a REQUIREMENTS phrase. If the longer
        "preferred candidate profile" were missing, every optional block on a
        Naukri posting would be read as mandatory.
        """
        assert classify_heading("Preferred Candidate Profile") is JobSectionType.NICE_TO_HAVE

    def test_a_trailing_ellipsis_does_not_defeat_a_known_heading(self):
        # "Who We Are…" appears verbatim in this corpus.
        assert classify_heading("Who We Are…") is JobSectionType.ABOUT

    def test_prose_beginning_with_a_heading_word_is_still_prose(self):
        """The guard that keeps the vocabulary from swallowing sentences.

        Without it, adding phrases like "about you" would start classifying
        ordinary narrative as section boundaries.
        """
        assert classify_heading("About you, we would love to hear more soon") is None
        assert classify_heading("Key skills are something we discuss at interview") is None


class TestBulletShapesRealPostingsUse:
    def test_a_dash_with_no_space_after_it(self):
        assert extract_bullets("-Design APIs\n-Own the deploy") == [
            "Design APIs",
            "Own the deploy",
        ]

    def test_a_middle_dot_marker(self):
        assert extract_bullets("· Build services\n· Review code") == [
            "Build services",
            "Review code",
        ]

    def test_words_second_level_o_bullet(self):
        """Word's nested bullet arrives as a literal "o " after a copy-paste."""
        assert extract_bullets("o Build services\no Review code") == [
            "Build services",
            "Review code",
        ]

    def test_a_line_merely_starting_with_or_is_not_a_bullet(self):
        # The cost of accepting `o` as a marker, guarded by requiring whitespace.
        assert extract_bullets("or the team will decide this at the review") == [
            "or the team will decide this at the review"
        ]

    def test_the_original_markers_still_work(self):
        # The point of the change was to add shapes, never to lose any.
        assert extract_bullets("- Build services\n* Review code\n1. Ship it") == [
            "Build services",
            "Review code",
            "Ship it",
        ]


class TestProseSections:
    """A recognised section whose body has no bullets.

    29% of the failures. The original rule returned nothing here, on the
    reasoning that prose would otherwise produce an array containing the whole
    posting — true of an *unlabelled* description, and not of a labelled section.
    """

    def test_a_paragraph_becomes_its_sentences(self):
        responsibilities, _ = arrays_of(
            "Role Overview\n"
            "We are seeking a Full Stack Data Engineer. You will build pipelines "
            "end to end. You will work with stakeholders across Finance."
        )
        assert responsibilities == [
            "We are seeking a Full Stack Data Engineer",
            "You will build pipelines end to end",
            "You will work with stakeholders across Finance",
        ]

    def test_items_run_together_with_no_separator(self):
        """The signature of list markup flattened away upstream.

        "...using FastAPI.Build and maintain..." — a full stop straight into a
        capital, with no space. Splitting on "period plus space" finds nothing.
        """
        responsibilities, _ = arrays_of(
            "Key Responsibilities\n"
            "Develop scalable REST APIs using FastAPI.Build crypto data pipelines."
            "Design and optimize PostgreSQL databases."
        )
        assert responsibilities == [
            "Develop scalable REST APIs using FastAPI",
            "Build crypto data pipelines",
            "Design and optimize PostgreSQL databases",
        ]

    def test_an_item_hard_wrapped_across_two_lines_is_rejoined(self):
        responsibilities, _ = arrays_of(
            "Key Responsibilities:\nDevelop and maintain\nPython applications.\n"
            "Write clean and\nefficient code."
        )
        assert responsibilities == [
            "Develop and maintain Python applications",
            "Write clean and efficient code",
        ]

    def test_a_version_number_is_not_a_sentence_boundary(self):
        responsibilities, _ = arrays_of(
            "Responsibilities\nNeeds 3.5 years of Python. Also Django 4.2 experience."
        )
        assert responsibilities == ["Needs 3.5 years of Python", "Also Django 4.2 experience"]

    def test_real_bullets_still_take_precedence_over_sentences(self):
        responsibilities, _ = arrays_of(
            "Responsibilities\n- Build the API\nSome trailing prose about the team."
        )
        assert responsibilities == ["Build the API"]


class TestNonBreakingSpaces:
    def test_a_posting_joined_by_nbsp_still_parses(self):
        """One real posting joins almost every word with U+00A0.

        `clean_description`'s `[ \\t]+` collapse never touched it, so the text
        reached the hash, the embedding and the parser with spacing that only
        looks like spacing.
        """
        # chr() rather than the literal: a no-break space is
        # indistinguishable from a space in source, which is the
        # whole reason it survived unnoticed in production.
        nbsp = chr(0x00A0)
        description = (
            f"Key{nbsp}Responsibilities\n"
            f"-{nbsp}Build{nbsp}services{nbsp}in{nbsp}Python\n"
            f"Requirements\n"
            f"-{nbsp}Five{nbsp}years{nbsp}of{nbsp}experience"
        )

        responsibilities, requirements = arrays_of(description)

        assert responsibilities == ["Build services in Python"]
        assert requirements == ["Five years of experience"]
        assert nbsp not in clean_description(description)


class TestNarrativePostingsStillYieldNothing:
    def test_a_posting_with_no_headings_produces_no_arrays(self):
        """The honest limit, asserted so it is not mistaken for a regression.

        70 of 292 live postings are narrative marketing copy with no structure to
        find. Inventing sections for them would put the employer's blurb into a
        "responsibilities" array, which is worse than leaving it empty — the
        document builder includes the description anyway.
        """
        responsibilities, requirements = arrays_of(
            "We help the world run better. At our company we keep it simple: you "
            "bring your best to us, and we bring out the best in you. We are "
            "builders touching eighty per cent of global commerce."
        )
        assert responsibilities == []
        assert requirements == []
