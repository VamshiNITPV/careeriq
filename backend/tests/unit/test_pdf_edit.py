"""Editing sentences inside an existing PDF (US-6.1).

The fixture is a PDF this project generates, so the test needs nobody's real
resume. What it cannot prove is behaviour on an arbitrary document from the
wild -- a designed two-column CV, a scan, a form. Those are handled by refusing
rather than guessing, which is what most of these tests are about.
"""

from __future__ import annotations

import io

import pdfplumber
import pymupdf
import pytest

from app.services.resume.pdf import build_resume_pdf
from app.services.resume.pdf_edit import NotEditableError, edit_pdf_in_place

SOURCE_TEXT = """Priya Raman
Senior Backend Engineer

Experience
Worked on the payments backend and handled settlement reconciliation daily.
Reduced p99 latency across the settlement service during peak load.

Skills
Python, Django, PostgreSQL
"""


# Named, because they are long enough that inlining them pushes every call site
# past the line limit and buries what each test is actually checking.
LATENCY = "Reduced p99 latency across the settlement service during peak load."
LATENCY_REWRITE = "Cut p99 latency under peak load."
PAYMENTS = "Worked on the payments backend and handled settlement reconciliation daily."
PAYMENTS_REWRITE = "Ran the payments backend and daily settlement."


def a_pdf() -> bytes:
    return build_resume_pdf(SOURCE_TEXT)


def text_of(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        return " ".join(
            " ".join((page.extract_text() or "").split()) for page in document.pages
        )


class TestReplacing:
    def test_the_new_wording_is_in_the_document(self) -> None:
        result = edit_pdf_in_place(
            a_pdf(),
            [(LATENCY, LATENCY_REWRITE)],
        )

        assert result.applied == 1
        assert "Cut p99 latency under peak load." in text_of(result.pdf)

    def test_the_old_wording_is_gone(self) -> None:
        """Redacted, not merely covered. Text left behind in the content stream
        would still be found by an ATS and by anyone who copies from the file --
        so the resume would say both things at once."""
        result = edit_pdf_in_place(
            a_pdf(),
            [(LATENCY, LATENCY_REWRITE)],
        )

        assert "Reduced p99 latency across" not in text_of(result.pdf)

    def test_the_rest_of_the_document_is_untouched(self) -> None:
        result = edit_pdf_in_place(
            a_pdf(),
            [(LATENCY, LATENCY_REWRITE)],
        )
        extracted = text_of(result.pdf)

        assert "Priya Raman" in extracted
        assert "Python, Django, PostgreSQL" in extracted
        assert "Worked on the payments backend" in extracted

    def test_several_sentences_at_once(self) -> None:
        result = edit_pdf_in_place(
            a_pdf(),
            [
                (PAYMENTS, PAYMENTS_REWRITE),
                (LATENCY, LATENCY_REWRITE),
            ],
        )

        extracted = text_of(result.pdf)
        assert result.applied == 2
        assert "Ran the payments backend and daily settlement." in extracted
        assert "Cut p99 latency under peak load." in extracted

    def test_the_replacement_keeps_the_original_left_edge(self) -> None:
        """The bullet and the indent live to the left of the text.

        Taking the left edge from the surrounding block instead started every
        replacement on top of its bullet glyph and wiped it -- which in a list is
        the first thing anyone notices.
        """
        before = pymupdf.open(stream=a_pdf(), filetype="pdf")
        left = before[0].search_for(LATENCY)[0].x0

        result = edit_pdf_in_place(a_pdf(), [(LATENCY, LATENCY_REWRITE)])

        after = pymupdf.open(stream=result.pdf, filetype="pdf")
        assert after[0].search_for(LATENCY_REWRITE)[0].x0 == pytest.approx(left, abs=1.0)


class TestRefusing:
    """A refusal is the safe outcome. A half-applied edit is a resume with a
    hole in it, which is what the first version of this produced."""

    def test_a_rewrite_needing_more_lines_is_refused(self) -> None:
        """Text is drawn from the top of its box down, so a replacement that
        wraps further than the text it replaced runs into the line beneath."""
        far_too_long = " ".join(["Reduced p99 latency across the settlement service"] * 6)

        result = edit_pdf_in_place(a_pdf(), [(LATENCY, far_too_long)])

        assert result.applied == 0
        assert len(result.skipped) == 1
        assert "too long" in result.skipped[0][1]

    def test_a_refused_edit_leaves_the_original_in_place(self) -> None:
        """Refusing must not mean deleting. The measurement happens before any
        redaction for exactly this reason."""
        result = edit_pdf_in_place(
            a_pdf(), [(LATENCY, " ".join(["much longer replacement text"] * 12))]
        )

        assert "Reduced p99 latency across" in text_of(result.pdf)

    def test_wording_that_is_not_there_is_reported(self) -> None:
        result = edit_pdf_in_place(a_pdf(), [("A sentence from a different resume.", "Anything.")])

        assert result.applied == 0
        assert "could not be located" in result.skipped[0][1]

    def test_one_refusal_does_not_block_the_others(self) -> None:
        result = edit_pdf_in_place(
            a_pdf(),
            [
                ("Not in this document at all.", "Anything."),
                (LATENCY, LATENCY_REWRITE),
            ],
        )

        assert result.applied == 1
        assert len(result.skipped) == 1
        assert "Cut p99 latency under peak load." in text_of(result.pdf)

    def test_something_that_is_not_a_pdf_raises(self) -> None:
        """Distinct from a sentence not fitting: the caller responds by
        rendering a fresh document instead."""
        with pytest.raises(NotEditableError):
            edit_pdf_in_place(b"this is not a pdf", [("a", "b")])

    def test_no_replacements_changes_nothing(self) -> None:
        result = edit_pdf_in_place(a_pdf(), [])

        assert result.applied == 0
        assert "Priya Raman" in text_of(result.pdf)


def baselines_of(pdf_bytes: bytes, needle: str) -> list[float]:
    """The pen positions the given text was drawn from."""
    page = pymupdf.open(stream=pdf_bytes, filetype="pdf")[0]
    first = needle.split()[0]
    found = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if first in span.get("text", ""):
                    found.append(round(float(span["origin"][1]), 2))
    return found


class TestItSitsOnTheOriginalBaseline:
    """The reported bug: replaced lines had visibly different spacing.

    `insert_textbox` fills a rectangle from the top using PyMuPDF's own leading,
    so the text landed near the old line rather than on it. These pin the
    replacement to the document's own pen positions.
    """

    def test_a_single_line_keeps_its_baseline(self) -> None:
        before = baselines_of(a_pdf(), LATENCY)
        assert before, "fixture did not contain the line"

        result = edit_pdf_in_place(a_pdf(), [(LATENCY, LATENCY_REWRITE)])

        after = baselines_of(result.pdf, LATENCY_REWRITE)
        assert after == pytest.approx(before, abs=0.5)

    def test_spacing_between_neighbours_is_unchanged(self) -> None:
        """The thing a reader actually sees. An absolute baseline can be right
        while the gap to the line above is wrong."""
        gap_before = baselines_of(a_pdf(), LATENCY)[0] - baselines_of(a_pdf(), PAYMENTS)[0]

        result = edit_pdf_in_place(a_pdf(), [(LATENCY, LATENCY_REWRITE)])

        gap_after = (
            baselines_of(result.pdf, LATENCY_REWRITE)[0]
            - baselines_of(result.pdf, PAYMENTS)[0]
        )
        assert gap_after == pytest.approx(gap_before, abs=0.5)


class TestThingsThatWouldCorruptThePage:
    def test_a_sentence_appearing_twice_is_refused(self) -> None:
        """Every match is redacted but only one is redrawn, so the other copy
        would simply vanish from the resume. Silent deletion of the user's own
        text is the worst outcome this module has."""
        repeated = "Managed the release process end to end."
        source = f"Priya Raman{chr(10)}{repeated}{chr(10)}Skills{chr(10)}{repeated}{chr(10)}"

        result = edit_pdf_in_place(build_resume_pdf(source), [(repeated, "Ran releases.")])

        assert result.applied == 0
        assert "appears more than once" in result.skipped[0][1]
        # Both copies still there.
        assert text_of(result.pdf).count("Managed the release process") == 2

    def test_a_rewrite_with_undrawable_characters_is_refused(self) -> None:
        """The stock faces are Latin-1. Left alone these render as `?` in
        somebody's resume."""
        result = edit_pdf_in_place(a_pdf(), [(LATENCY, "Cut latency 中文 under load.")])

        assert result.applied == 0
        assert "cannot show" in result.skipped[0][1]

    def test_typographic_characters_are_folded_rather_than_refused(self) -> None:
        """An em dash is not a reason to lose a suggestion -- a hyphen says the
        same thing and the face can draw it."""
        result = edit_pdf_in_place(
            a_pdf(), [(LATENCY, "Cut latency — under “peak” load.")]
        )

        assert result.applied == 1
        extracted = text_of(result.pdf)
        assert "?" not in extracted
        assert "under" in extracted

    def test_two_changes_on_one_line_keep_only_the_first(self) -> None:
        """Both would be drawn from their own start with their own wrapping, and
        overlap into unreadable text."""
        source = f"Priya Raman{chr(10)}Alpha beta gamma. Delta epsilon zeta.{chr(10)}"

        result = edit_pdf_in_place(
            build_resume_pdf(source),
            [("Alpha beta gamma.", "Alpha one."), ("Delta epsilon zeta.", "Delta two.")],
        )

        assert result.applied == 1
        assert any("already applies to that line" in why for _, why in result.skipped)

    def test_line_art_survives_the_edit(self) -> None:
        """Redaction's defaults strip line art that merely *touches* the
        rectangle, which would take the rule under a section heading with it and
        leave the page broken for reasons unrelated to the sentence."""
        document = pymupdf.open(stream=a_pdf(), filetype="pdf")
        page = document[0]
        rect = page.search_for(LATENCY)[0]
        page.draw_line((rect.x0, rect.y1 + 1), (rect.x1, rect.y1 + 1))
        with_rule = document.tobytes()
        before = len(pymupdf.open(stream=with_rule, filetype="pdf")[0].get_drawings())

        result = edit_pdf_in_place(with_rule, [(LATENCY, LATENCY_REWRITE)])

        after = len(pymupdf.open(stream=result.pdf, filetype="pdf")[0].get_drawings())
        assert result.applied == 1
        assert after == before

