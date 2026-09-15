"""Replace sentences inside the user's own PDF, keeping their layout.

`pdf.py` renders tailored text as a clean new document. This does the other
thing: takes the PDF they designed and swaps the accepted sentences in place, so
what comes back still looks like their resume.

## Measure first, then redact

A PDF has fixed geometry. Removing a sentence and writing a longer one back into
the same box can overflow it, and PyMuPDF's answer to "it did not fit" is to
draw nothing at all -- leaving a bullet point with empty space after it, which
is how the first attempt at this produced a resume with a hole in it.

So every replacement is measured against its box **before** anything is redacted,
and a replacement that cannot be made is refused rather than half-applied. The
caller is told which ones failed and falls back to the generated document.

## What this cannot do

**Reflow.** If the rewrite is shorter, the space the old text occupied stays
blank; if it is longer, it shrinks to fit rather than pushing the rest of the
page down. Text below never moves, because moving it would mean re-laying out a
document we did not author.

**Match the font exactly.** Embedded fonts in a real resume are *subsets* -- the
LaTeX file this was built against carries `DGBDFT+CMR10`, containing only the
glyphs that document already uses. New words routinely need glyphs that are not
in there, so replacements are drawn in a stock face chosen to match the
original's style. Close, and visibly not identical under inspection.

Both are stated plainly to the user rather than hidden, because a resume that
looks subtly wrong is worse than one that is honestly different.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pymupdf

#: Smallest we will shrink replacement text before giving up.
#:
#: Below this it stops matching the surrounding lines closely enough to pass as
#: the same document, which is the only reason to be editing in place at all.
_MIN_FONT_SIZE = 8.0

#: Slack given to the box so `insert_textbox` accepts text that fits.
#:
#: It reserves line height plus leading, so a box matching the old text exactly
#: is a few points short and refuses replacements that plainly fit. Harmless
#: because line count is checked separately: text is drawn from the top down, so
#: a taller box never moves anything.
_EXTRA_HEIGHT = 8.0

#: Stock faces. The original's own font cannot be reused -- see the docstring.
_SERIF = "tiro"
_SANS = "helv"

#: Substrings that mark an embedded font as serif. `CM` is Computer Modern,
#: which is what every LaTeX resume uses and what the first real document here
#: turned out to be.
_SERIF_HINTS = ("CM", "Times", "Serif", "Roman", "Georgia", "Garamond", "Minion")


@dataclass(frozen=True, slots=True)
class EditResult:
    pdf: bytes
    applied: int
    #: Sentences that could not be placed, with the reason.
    skipped: tuple[tuple[str, str], ...]


class NotEditableError(ValueError):
    """The document cannot be edited in place at all.

    Distinct from "one sentence did not fit": this means the file is not a PDF
    we can work with, and the caller should render a fresh document instead.
    """


def _face_for(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[str, float]:
    """The stock face and size closest to whatever sits in `rect`.

    Falls back to serif at 10pt, which is what a resume is unless it says
    otherwise.
    """
    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if not pymupdf.Rect(span["bbox"]).intersects(rect):
                    continue
                name = span.get("font", "")
                serif = any(hint.lower() in name.lower() for hint in _SERIF_HINTS)
                return (_SERIF if serif else _SANS), float(span.get("size", 10.0))
    return _SERIF, 10.0


def _writable_box(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> pymupdf.Rect:
    """The area a replacement may occupy.

    The union of the matched rectangles is the *old text's* outline, which is
    the wrong shape to measure against: a rewrite one word wider gets refused
    even when it is shorter overall, because the stock face has different
    metrics from the embedded one. What is actually available is the paragraph's
    column, so the box takes its horizontal extent from the containing block.

    Vertically it grows downward into the gap before the next line, and no
    further. `insert_textbox` reserves a full line height plus leading, so a box
    sized to the old text's outline is a couple of points short of holding even
    smaller replacement text -- which refused edits that would have fitted
    comfortably. Stopping at the next line's top is what keeps that from
    becoming an overlap.
    """
    box = rects[0]
    for rect in rects[1:]:
        box = box | rect

    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        outline = pymupdf.Rect(block["bbox"])
        if outline.contains(rects[0]):
            # Right edge from the block, left edge from the text itself. Taking
            # both from the block starts the replacement where the bullet glyph
            # sits and paints over it -- every edited line lost its bullet and
            # its indent, which is instantly visible in a list.
            box = pymupdf.Rect(rects[0].x0, box.y0, outline.x1, box.y1)
            break

    # The next line below, wherever it is. Nothing may be drawn past it.
    ceiling = page.rect.y1
    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        for line in block["lines"]:
            top = pymupdf.Rect(line["bbox"]).y0
            if top >= box.y1 - 0.5:
                ceiling = min(ceiling, top)

    # Room for `insert_textbox` to accept the text at all. Safe because the
    # caller has already established the replacement needs no more lines than
    # the original -- so nothing is ever *drawn* below where the old text ended,
    # however tall the box is told it may be.
    box.y1 = max(box.y1 + _EXTRA_HEIGHT, min(ceiling, box.y1) + _EXTRA_HEIGHT)
    return box


def _fit_size(
    box: pymupdf.Rect, lines_available: int, text: str, font: str, size: float
) -> float | None:
    """Largest size at or below `size` whose text needs no more lines than the
    original occupied, or None.

    Line count is the thing that matters, not the box. Text is drawn from the
    top of the box down, so a taller box does not move the first line -- what
    pushes into the row beneath is a replacement that *wraps* further than the
    text it replaced. Measuring lines directly says exactly that, where asking
    `insert_textbox` whether it fits conflates it with the box being a couple of
    points short of its own leading.
    """
    usable = box.width
    if usable <= 0:
        return None

    trial = size
    while trial >= _MIN_FONT_SIZE:
        width = pymupdf.get_text_length(text, fontname=font, fontsize=trial)
        # A tenth of slack: the real wrap happens at word boundaries, so a line
        # rarely uses its full width and this estimate runs slightly optimistic.
        needed = math.ceil(width / (usable * 0.9))
        if max(1, needed) <= lines_available:
            return trial
        trial -= 0.5
    return None


def edit_pdf_in_place(pdf_bytes: bytes, replacements: list[tuple[str, str]]) -> EditResult:
    """Swap each `(original, suggested)` pair inside `pdf_bytes`.

    Returns the edited document plus what could not be done. Raises
    `NotEditableError` only when the file itself is unusable.
    """
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - depends on the stored bytes
        raise NotEditableError(f"This file could not be opened as a PDF: {exc}") from exc

    if document.page_count == 0:
        raise NotEditableError("This PDF has no pages.")

    # Planned across the whole document first. Redacting as we go would mean a
    # later failure leaves earlier sentences already removed.
    planned: list[tuple[pymupdf.Page, list[pymupdf.Rect], pymupdf.Rect, str, str, float]] = []
    skipped: list[tuple[str, str]] = []

    for original, suggested in replacements:
        located = False
        for page in document:
            rects = page.search_for(original)
            if not rects:
                continue
            located = True

            box = _writable_box(page, rects)
            font, size = _face_for(page, rects[0])
            fitted = _fit_size(box, len(rects), suggested, font, size)
            if fitted is None:
                skipped.append((original, "the rewrite is too long for the space it would replace"))
            else:
                planned.append((page, rects, box, suggested, font, fitted))
            break

        if not located:
            # Usually because the sentence spans a column or page break, where
            # the extracted text reads continuously but the page geometry does
            # not.
            skipped.append((original, "that wording could not be located in the document"))

    for page, rects, _, _, _, _ in planned:
        for rect in rects:
            page.add_redact_annot(rect)

    # Once per page, not once per rect: applying redactions rewrites the page's
    # content stream, and doing that repeatedly invalidates the rectangles still
    # queued against it.
    for page in {entry[0] for entry in planned}:
        page.apply_redactions()

    for page, _, box, suggested, font, size in planned:
        page.insert_textbox(box, suggested, fontsize=size, fontname=font, align=0)

    return EditResult(
        pdf=document.tobytes(), applied=len(planned), skipped=tuple(skipped)
    )
