"""Tests for text extraction, section detection, and skill matching (ml.md section 2)."""

from __future__ import annotations

import pytest

from app.data.skill_taxonomy import SEED_SKILLS, normalize_skill_text
from app.services.file_validation import DocumentType
from app.services.resume.extraction import UnextractableDocumentError, extract_text
from app.services.resume.sections import (
    SectionType,
    classify_heading,
    detect_sections,
    section_map,
)
from app.services.resume.skill_extraction import (
    REVIEW_THRESHOLD,
    build_matcher,
    extract_skills,
    parse_skills_list,
)
from tests.fixtures.documents import (
    SAMPLE_RESUME,
    UNSTRUCTURED_RESUME,
    build_docx,
    build_docx_with_table,
    build_image_only_pdf,
    build_pdf,
)


def taxonomy() -> dict[str, list[str]]:
    return {s.name: [s.normalized_name, *s.normalized_aliases] for s in SEED_SKILLS}


# ---------------------------------------------------------------- extraction
class TestTextExtraction:
    def test_extracts_from_pdf(self) -> None:
        result = extract_text(content=build_pdf(), document_type=DocumentType.PDF)

        assert "PRIYA SHARMA" in result.text
        assert "FastAPI" in result.text
        assert result.extractor == "pdfplumber"
        assert result.character_count > 500

    def test_extracts_from_docx(self) -> None:
        result = extract_text(content=build_docx(), document_type=DocumentType.DOCX)

        assert "PRIYA SHARMA" in result.text
        assert "TECHNICAL SKILLS" in result.text
        assert result.extractor == "python-docx"

    def test_reads_docx_tables(self) -> None:
        """Table cells are not in `paragraphs`.

        Resumes routinely put skills in a table, so an extractor that reads only
        paragraphs drops exactly the content most worth having.
        """
        result = extract_text(content=build_docx_with_table(), document_type=DocumentType.DOCX)

        assert "PostgreSQL" in result.text
        assert "Kubernetes" in result.text

    def test_rejects_a_pdf_with_no_text(self) -> None:
        # Stands in for a scanned resume. Must fail loudly rather than produce
        # an empty profile the user cannot explain.
        with pytest.raises(UnextractableDocumentError) as exc:
            extract_text(content=build_image_only_pdf(), document_type=DocumentType.PDF)
        assert exc.value.code == "UNEXTRACTABLE_DOCUMENT"

    def test_rejects_a_corrupt_pdf(self) -> None:
        broken = b"%PDF-1.4\nbroken" + b"\x00" * 500
        with pytest.raises(UnextractableDocumentError):
            extract_text(content=broken, document_type=DocumentType.PDF)

    def test_normalizes_ligatures(self) -> None:
        # pdfplumber returns real ligature characters; left alone they turn
        # "workflow" into a token no skill lookup will ever match.
        result = extract_text(
            content=build_docx("ﬁrst\n" + SAMPLE_RESUME), document_type=DocumentType.DOCX
        )
        assert "ﬁ" not in result.text
        assert "first" in result.text


# ---------------------------------------------------------------- sections
class TestHeadingClassification:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("EXPERIENCE", SectionType.EXPERIENCE),
            ("Work Experience", SectionType.EXPERIENCE),
            ("PROFESSIONAL EXPERIENCE", SectionType.EXPERIENCE),
            ("Education", SectionType.EDUCATION),
            ("TECHNICAL SKILLS", SectionType.SKILLS),
            ("Skills:", SectionType.SKILLS),
            ("--- PROJECTS ---", SectionType.PROJECTS),
            ("CERTIFICATIONS", SectionType.CERTIFICATIONS),
            ("Professional Summary", SectionType.SUMMARY),
        ],
    )
    def test_recognises_common_headings(self, line: str, expected: SectionType) -> None:
        assert classify_heading(line) is expected

    @pytest.mark.parametrize(
        "line",
        [
            "I used these skills daily in my role",
            "My experience includes building distributed systems",
            "Completed my education at NIT with a focus on systems",
            "",
            "   ",
        ],
    )
    def test_prose_containing_a_heading_word_is_not_a_heading(self, line: str) -> None:
        """Requires an exact match, not a substring.

        A substring search would treat every sentence mentioning "experience" as
        a section boundary and shred the document.
        """
        assert classify_heading(line) is None

    def test_long_lines_are_never_headings(self) -> None:
        assert classify_heading("skills " * 30) is None

    def test_longest_phrase_wins(self) -> None:
        # "technical skills" must not be claimed by the shorter "skills" entry.
        assert classify_heading("TECHNICAL SKILLS") is SectionType.SKILLS


class TestSectionDetection:
    def test_splits_a_resume_into_sections(self) -> None:
        sections = detect_sections(SAMPLE_RESUME)
        found = {s.type for s in sections}

        assert SectionType.SKILLS in found
        assert SectionType.EXPERIENCE in found
        assert SectionType.EDUCATION in found
        assert SectionType.PROJECTS in found

    def test_content_before_the_first_heading_becomes_contact(self) -> None:
        sections = detect_sections(SAMPLE_RESUME)
        contact = next(s for s in sections if s.type is SectionType.CONTACT)

        assert "priya.sharma@example.com" in contact.text

    def test_spans_point_back_into_the_source_text(self) -> None:
        # US-2.3 AC2 requires extracted data to cite where it came from, which
        # is only possible if the offsets are correct.
        for section in detect_sections(SAMPLE_RESUME):
            assert 0 <= section.start <= section.end <= len(SAMPLE_RESUME)

    def test_skills_section_contains_the_skills(self) -> None:
        by_type = section_map(detect_sections(SAMPLE_RESUME))
        skills_text = by_type[SectionType.SKILLS]

        assert "Python" in skills_text
        assert "Postgres" in skills_text
        # Must not have swallowed the following section.
        assert "WORK EXPERIENCE" not in skills_text

    def test_unstructured_text_yields_one_unknown_section(self) -> None:
        sections = detect_sections(UNSTRUCTURED_RESUME)
        assert len(sections) == 1
        assert sections[0].type is SectionType.UNKNOWN

    def test_empty_input(self) -> None:
        assert detect_sections("") == []

    def test_repeated_sections_are_merged_not_overwritten(self) -> None:
        text = "SKILLS\nPython\n\nEXPERIENCE\nWork\n\nTECHNICAL SKILLS\nDocker\n"
        by_type = section_map(detect_sections(text))

        assert "Python" in by_type[SectionType.SKILLS]
        assert "Docker" in by_type[SectionType.SKILLS]


# ---------------------------------------------------------------- skills
class TestSkillExtraction:
    def _extract(self, text: str = SAMPLE_RESUME):
        matcher = build_matcher(taxonomy())
        return extract_skills(
            matcher=matcher,
            sections=section_map(detect_sections(text)),
            full_text=text,
        )

    def test_finds_skills_by_canonical_name(self) -> None:
        names = {c.canonical_name for c in self._extract()}

        assert "Python" in names
        assert "FastAPI" in names
        assert "Docker" in names

    def test_resolves_aliases_to_canonical_names(self) -> None:
        """The taxonomy's entire purpose.

        The resume says "Postgres" and "K8s"; matching must produce PostgreSQL
        and Kubernetes, or nothing downstream can compare a candidate to a job.
        """
        names = {c.canonical_name for c in self._extract()}

        assert "PostgreSQL" in names
        assert "Kubernetes" in names

    def test_skills_section_scores_higher_than_prose(self) -> None:
        # A term in an explicit skills list is a claim; the same term in a
        # sentence may be incidental.
        candidates = {c.canonical_name: c for c in self._extract()}
        assert candidates["Python"].confidence > REVIEW_THRESHOLD

    def test_longer_names_win_over_substrings(self) -> None:
        text = "SKILLS\nReact Native, Node.js\n"
        names = {c.canonical_name for c in self._extract(text)}

        # "React Native" must not be recorded as plain "React".
        assert "React Native" in names
        assert "React" not in names

    def test_matches_names_containing_punctuation(self) -> None:
        r"""C++, C#, .NET and Node.js break naive \b word boundaries.

        `\b` is defined against `\w`, so `\bc\+\+\b` never matches — there is no
        word boundary after `+`. Getting these wrong silently drops some of the
        most common skills on a resume.
        """
        text = "SKILLS\nC++, C#, .NET, Node.js\n"
        names = {c.canonical_name for c in self._extract(text)}

        assert "C++" in names
        assert "C#" in names
        assert ".NET" in names
        assert "Node.js" in names

    def test_does_not_match_inside_a_larger_word(self) -> None:
        # "Rust" must not be found inside "frustrating", and "Go" not inside
        # "Google" — precision is weighted above recall (ml.md section 2.4).
        text = "SUMMARY\nIt was frustrating to google the answer.\n"
        names = {c.canonical_name for c in self._extract(text)}

        assert "Rust" not in names
        assert "Go" not in names

    def test_case_insensitive(self) -> None:
        names = {c.canonical_name for c in self._extract("SKILLS\npython, DOCKER, PostgreSQL\n")}
        assert {"Python", "Docker", "PostgreSQL"} <= names

    def test_falls_back_to_full_text_when_no_sections_exist(self) -> None:
        candidates = self._extract(UNSTRUCTURED_RESUME)
        names = {c.canonical_name for c in candidates}

        assert "Python" in names
        assert "PostgreSQL" in names
        # Lower confidence, because an unstructured match deserves less trust.
        assert all(c.confidence < 0.7 for c in candidates)

    def test_repeated_mentions_raise_confidence_but_are_capped(self) -> None:
        candidates = self._extract()
        assert all(c.confidence <= 0.99 for c in candidates)

    def test_results_are_sorted_by_confidence(self) -> None:
        confidences = [c.confidence for c in self._extract()]
        assert confidences == sorted(confidences, reverse=True)


class TestSkillsListParsing:
    def test_splits_on_common_separators(self) -> None:
        terms = parse_skills_list("Python, JavaScript; Go | Rust\nElixir")
        assert {"python", "javascript", "go", "rust", "elixir"} <= set(terms)

    def test_drops_sentences(self) -> None:
        terms = parse_skills_list("I have worked extensively with many different technologies here")
        assert terms == []

    def test_deduplicates(self) -> None:
        assert parse_skills_list("Python, python, PYTHON") == ["python"]


class TestTaxonomyData:
    def test_normalization_keeps_meaningful_punctuation(self) -> None:
        # Stripping these collapses C++ into C, C# into C, and .NET into net.
        assert normalize_skill_text("C++") == "c++"
        assert normalize_skill_text("C#") == "c#"
        assert normalize_skill_text(".NET") == ".net"
        assert normalize_skill_text("Node.js") == "node.js"

    def test_normalized_names_are_unique(self) -> None:
        # A duplicate would violate the unique index at seed time.
        normalized = [s.normalized_name for s in SEED_SKILLS]
        assert len(normalized) == len(set(normalized))

    def test_aliases_never_repeat_the_canonical_name(self) -> None:
        for skill in SEED_SKILLS:
            assert skill.normalized_name not in skill.normalized_aliases

    def test_every_parent_exists(self) -> None:
        names = {s.name for s in SEED_SKILLS}
        for skill in SEED_SKILLS:
            if skill.parent is not None:
                assert skill.parent in names, f"{skill.name} references unknown parent"

    def test_no_alias_collides_across_skills(self) -> None:
        """A colliding alias makes matching ambiguous and order-dependent."""
        seen: dict[str, str] = {}
        for skill in SEED_SKILLS:
            for alias in skill.normalized_aliases:
                assert alias not in seen, f"'{alias}' claimed by {seen.get(alias)} and {skill.name}"
                seen[alias] = skill.name
