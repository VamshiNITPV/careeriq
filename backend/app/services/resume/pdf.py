"""Render tailored resume text as a PDF (US-6.1).

## What this is not

**Not a reproduction of the document the user uploaded.** Their PDF has fonts,
columns, rules and spacing we only ever saw as extracted text, and re-typesetting
a design from its own output produces something subtly broken -- the kind of file
someone sends to an employer once and then stops trusting us. We do not attempt
it and should not pretend to.

What this produces is a clean, legible document carrying the tailored wording:
one column, generous margins, a single readable face. It is a resume, not a
facsimile.

## Why a vendored font

fpdf2's built-in faces are latin-1. That encoding has no bullet, so every `*`
in a resume renders as `?`, along with every em dash, curly quote, rupee sign
and accented name. `tests/fixtures/documents.py` papers over this with
`encode("latin-1", "replace")`, which is fine for a fixture and would be a
defect in a user's document.

So `assets/fonts/DejaVuSans.ttf` is vendored and registered here. Shipping the
file rather than installing an OS package means the output is identical on a
developer machine, in CI and on any future host, with no system dependency to
go missing.

## Machine-readable by construction

Single column, no tables, real text rather than an image. An applicant tracking
system reads it by extracting the text, which is exactly what the round-trip
test does -- `pdfplumber` reads back what was written.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

#: The vendored Unicode face. See the module docstring for why it is vendored.
FONT_PATH = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "DejaVuSans.ttf"

_FONT_NAME = "DejaVu"
#: Points. Small enough to fit a dense resume, large enough to read on paper.
_FONT_SIZE = 10
#: Millimetres. A4 rather than Letter, matching where this is used.
_MARGIN_MM = 15
#: Line height in millimetres, a little over the font size for legibility.
_LINE_MM = 5.0
#: Vertical space a blank line becomes. Less than a full line, because runs of
#: blank lines in extracted text are usually layout artefacts rather than
#: intended gaps, and reproducing every one of them leaves a very sparse page.
_BLANK_LINE_MM = 2.5


class EmptyDocumentError(ValueError):
    """There was no text to render.

    Raised rather than emitting a blank page: a zero-content PDF looks like a
    successful export right up until someone opens it.
    """


def build_resume_pdf(text: str, *, title: str = "Resume") -> bytes:
    """Lay `text` out as a single-column PDF and return its bytes.

    Pure: no database, no network, no filesystem beyond reading the font. That
    is what lets the round-trip test run anywhere.
    """
    if not text.strip():
        raise EmptyDocumentError("There is no text to put in the document.")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN_MM)
    # Set before the first page, so it lands in the document metadata rather
    # than being silently dropped.
    pdf.set_title(title)
    pdf.add_font(_FONT_NAME, "", str(FONT_PATH))
    pdf.set_font(_FONT_NAME, size=_FONT_SIZE)
    pdf.add_page()

    for line in text.splitlines():
        if not line.strip():
            pdf.ln(_BLANK_LINE_MM)
            continue

        # `multi_cell`, not `cell`. A resume line longer than the text width --
        # most summary sentences -- runs off the page with `cell` and is simply
        # lost, which is how the test fixture behaves and must not be how a
        # user's document behaves.
        #
        # Leading whitespace is stripped because extracted PDF text carries the
        # indentation of the original layout, and reproducing it here indents
        # against a margin that no longer means anything.
        pdf.multi_cell(w=0, h=_LINE_MM, text=line.strip(), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
