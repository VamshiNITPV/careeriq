"""Tests for skill inference from prose (ADR-012, inference.py).

The behavioural tests matter, but the safety tests matter more: an inferred
skill is the system's interpretation of a candidate's words, not something the
candidate said. If one ever reached a profile without a human confirming it, the
system would be asserting something about a person that they did not claim.
"""

from __future__ import annotations

import pytest

from app.services.resume.inference import (
    INFERENCE_RULES,
    MAX_INFERENCE_CONFIDENCE,
    infer_skills,
)
from app.services.resume.sections import SectionType
from app.services.resume.skill_extraction import REVIEW_THRESHOLD


def infer(text: str, section: SectionType = SectionType.EXPERIENCE, found: set[str] | None = None):
    return infer_skills(sections={section: text}, already_found=found or set())


class TestSafetyProperties:
    """These are the tests that stop the feature becoming a liability."""

    def test_no_inference_can_ever_be_auto_accepted(self) -> None:
        """The single most important property in this module.

        Every rule's confidence must sit below the threshold at which the
        pipeline writes a skill to a profile. If one crept above it, the system
        would start claiming skills on a candidate's behalf — the exact failure
        ADR-012 exists to prevent.
        """
        for rule in INFERENCE_RULES:
            assert rule.confidence <= MAX_INFERENCE_CONFIDENCE, rule.skill
            assert rule.confidence < REVIEW_THRESHOLD, rule.skill

    def test_the_cap_is_below_the_acceptance_threshold(self) -> None:
        assert MAX_INFERENCE_CONFIDENCE < REVIEW_THRESHOLD

    def test_every_suggestion_carries_its_evidence(self) -> None:
        # Without the sentence, a suggestion is an unexplained assertion and the
        # user has no basis to accept or reject it.
        results = infer("Built responsive user interfaces and deployed to production.")

        assert results
        for suggestion in results:
            assert suggestion.evidence.strip()
            assert len(suggestion.evidence) <= 240

    def test_evidence_is_a_real_substring_of_the_input(self) -> None:
        # Quoting something the resume does not say would be fabrication in the
        # explanation itself.
        text = "Built responsive user interfaces for the customer portal."
        for suggestion in infer(text):
            assert suggestion.evidence in text


class TestNoDoubleCounting:
    def test_skills_already_matched_are_not_suggested(self) -> None:
        # Offering to add something already on the profile is noise, and would
        # make the same skill appear twice with different confidences.
        text = "Deployed the service and debugged production issues."

        without = {s.canonical_name for s in infer(text)}
        with_found = {s.canonical_name for s in infer(text, found={"Deployment"})}

        assert "Deployment" in without
        assert "Deployment" not in with_found

    def test_the_skills_section_is_not_used_as_evidence(self) -> None:
        """A skills list is an explicit claim, matched directly.

        Inferring from it would double-count: the same term would appear as both
        a match and a suggestion.
        """
        assert infer("Testing, debugging, deployment", section=SectionType.SKILLS) == []

    def test_one_suggestion_per_skill_even_with_repeated_evidence(self) -> None:
        text = (
            "Deployed the API to staging.\n"
            "Deployed the frontend to production.\n"
            "Deployed a hotfix on Friday."
        )
        names = [s.canonical_name for s in infer(text)]
        assert names.count("Deployment") == 1


class TestInferenceRules:
    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("Built responsive user interfaces for mobile.", "Responsive Web Design"),
            ("Implemented server-side functionality in Python.", "Backend Development"),
            ("Developed and consumed REST APIs for the client.", "API Development"),
            ("Collaborated on database design and schema modelling.", "Database Design"),
            ("Preprocessed and trained a large CT dataset.", "Data Preprocessing"),
            ("Trained a CNN model on 500 patient scans.", "Model Training"),
            ("Applied deep learning to medical image segmentation.", "Image Segmentation"),
            ("Deployed the application to Vercel.", "Deployment"),
            ("Wrote unit tests for the payments service.", "Software Testing"),
            ("Debugged and resolved production incidents.", "Debugging"),
            ("Reduced page load time by optimising queries.", "Performance Optimization"),
            ("Collaborated with a 3-person team.", "Teamwork"),
        ],
    )
    def test_recognises_the_phrasings_resumes_use(self, sentence: str, expected: str) -> None:
        assert expected in {s.canonical_name for s in infer(sentence)}

    def test_rules_are_narrow_enough_to_be_useful(self) -> None:
        """A rule that fires on any mention of its topic is worse than none.

        "The database was slow" is not evidence of database design skill;
        suggesting it would train the user to ignore suggestions entirely.
        """
        names = {s.canonical_name for s in infer("The database was slow that week.")}

        assert "Database Design" not in names
        assert "Database Management" not in names

    def test_unrelated_prose_suggests_nothing(self) -> None:
        text = "Enjoys hiking and photography. Fluent in three languages."
        assert infer(text) == []

    def test_results_are_ordered_by_confidence(self) -> None:
        text = (
            "Built responsive user interfaces, deployed to Vercel, "
            "and collaborated with the team on database design."
        )
        confidences = [s.confidence for s in infer(text)]
        assert confidences == sorted(confidences, reverse=True)


class TestEvidenceSections:
    @pytest.mark.parametrize(
        "section",
        [SectionType.EXPERIENCE, SectionType.PROJECTS, SectionType.SUMMARY],
    )
    def test_infers_from_sections_describing_what_was_done(self, section: SectionType) -> None:
        assert infer("Deployed the application to production.", section=section)

    @pytest.mark.parametrize(
        "section",
        [SectionType.EDUCATION, SectionType.CONTACT, SectionType.SKILLS],
    )
    def test_ignores_sections_that_do_not_describe_work(self, section: SectionType) -> None:
        assert infer("Deployed the application to production.", section=section) == []
