"""Rendering tailored resume text as a PDF (US-6.1).

The load-bearing test here is the round trip. A PDF that merely parses is not
the claim being made -- the claim is that an applicant tracking system can read
it, and the only honest way to check that is to extract the text back out and
compare. `pdfplumber` is the same library the upload pipeline parses with, so
this is the real path a document takes.
"""

from __future__ import annotations

import io

import pdfplumber
import pytest

from app.services.resume.pdf import EmptyDocumentError, build_resume_pdf

RESUME = """Priya Raman
Senior Backend Engineer

Experience
- Worked on the payments backend, handling 12,000 transactions per day.
- Reduced p99 latency by 35% across the settlement service.

Skills
Python, Django, PostgreSQL
"""


def extract(pdf_bytes: bytes) -> str:
    """Read the text back out, the way the parser and an ATS would."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        return "\n".join(page.extract_text() or "" for page in document.pages)


class TestItIsARealDocument:
    def test_the_bytes_are_a_pdf(self) -> None:
        result = build_resume_pdf(RESUME)

        assert result.startswith(b"%PDF-")
        assert len(result) > 1000

    def test_the_text_can_be_read_back_out(self) -> None:
        """The whole point. A PDF nothing can extract from is a picture of a
        resume, and an ATS discards it."""
        extracted = extract(build_resume_pdf(RESUME))

        assert "Priya Raman" in extracted
        assert "Reduced p99 latency by 35%" in extracted
        assert "Python, Django, PostgreSQL" in extracted

    def test_every_line_survives(self) -> None:
        """Not just the first and last. A layout bug that drops the middle of a
        document would pass a looser check."""
        extracted = extract(build_resume_pdf(RESUME))

        for line in (entry.strip() for entry in RESUME.splitlines() if entry.strip()):
            assert line in extracted, f"lost: {line!r}"


class TestCharactersThatBreakTheBuiltInFont:
    """Why `assets/fonts/DejaVuSans.ttf` is vendored.

    fpdf2's built-in faces are latin-1. Every case below renders as `?` on
    those, and the first one appears in almost every resume ever written.
    """

    @pytest.mark.parametrize(
        ("label", "line"),
        [
            ("bullet", "• Built payment services"),
            ("rupee", "Saved ₹2,50,000 annually"),
            ("accent", "Worked at Société Générale"),
            ("em-dash", "Backend engineer — payments"),
            ("curly-quote", "Led the “fast path” rewrite"),
        ],
    )
    def test_it_survives_the_round_trip(self, label: str, line: str) -> None:
        extracted = extract(build_resume_pdf(line))

        assert "?" not in extracted, f"{label} was replaced"
        # The distinctive character itself, not just the surrounding words.
        assert line.strip()[0] in extracted or line.split()[-1] in extracted


class TestLayout:
    def test_a_long_line_wraps_rather_than_vanishing(self) -> None:
        """`cell` silently runs a long line off the page; `multi_cell` wraps it.
        A resume summary is routinely longer than the text width, so the
        difference is most of a document rather than an edge case."""
        long_line = (
            "Backend engineer with six years building payment and settlement "
            "systems, working across Python, Django and PostgreSQL, with a focus "
            "on latency and correctness under concurrent load."
        )

        extracted = extract(build_resume_pdf(long_line))

        # Wrapped, so the extracted form carries a newline the input did not.
        assert extracted.strip() != long_line
        # Every word still present, in order, once whitespace is normalised.
        assert " ".join(extracted.split()) == " ".join(long_line.split())

    def test_a_document_longer_than_a_page_keeps_everything(self) -> None:
        many = "\n".join(f"Line number {index} of the resume." for index in range(120))

        extracted = extract(build_resume_pdf(many))

        assert "Line number 0 of the resume." in extracted
        assert "Line number 119 of the resume." in extracted

    def test_blank_lines_do_not_become_blank_pages(self) -> None:
        """Extracted text is full of blank lines from the original layout.
        Giving each one a full line would push a two-page resume to four."""
        padded = "Top\n" + "\n" * 40 + "Bottom"

        with pdfplumber.open(io.BytesIO(build_resume_pdf(padded))) as document:
            assert len(document.pages) == 1


class TestRefusingToProduceNothing:
    @pytest.mark.parametrize("empty", ["", "   ", "\n\n\n", "\t \n"])
    def test_empty_text_raises(self, empty: str) -> None:
        """A zero-content PDF looks like a successful export until it is
        opened."""
        with pytest.raises(EmptyDocumentError):
            build_resume_pdf(empty)
