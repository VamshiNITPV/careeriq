"""Replace sentences inside the user's own PDF, keeping their layout.

`pdf.py` renders tailored text as a clean new document. This does the other
thing: takes the PDF they designed and swaps the accepted sentences in place, so
what comes back still looks like their resume.

## Draw on the document's own baselines

A PDF line has a baseline -- the pen position its glyphs were drawn from. The
first version of this placed replacements with `insert_textbox`, which fills a
rectangle from the top down using PyMuPDF's own leading, so the new text landed
near the old line rather than on it, and a two-line replacement used PyMuPDF's
spacing instead of the document's. Visible immediately as a step in the line
spacing.

Every replacement line is now drawn at the baseline the original line used,
read from the span's `origin`. The spacing is the document's by construction,
because it *is* the document's -- nothing here computes a layout, so nothing
here can disagree with one.

## Measure first, then redact

Removing a sentence and writing a longer one back can overflow the space, and
PyMuPDF's answer to "it did not fit" is to draw nothing at all -- leaving a
bullet with a hole where a sentence used to be. Everything is measured against
the real line geometry **before** anything is redacted, and a replacement that
cannot be made is refused rather than half-applied.

Refusing is cheap: `apply_suggestions` falls back to the generated document,
which always carries the same words. Corrupting a line the user never chose to
change is not cheap, so every doubtful case refuses.

## What it refuses, and why each one would corrupt the page

- **The sentence appears more than once.** `search_for` returns every match, and
  redacting all of them while drawing into one deletes a copy of the user's text
  outright.
- **Other text shares the sentence's last line.** Redaction removes any glyph
  touching the rectangle, so a neighbour can be eaten by a sub-point overlap --
  and a longer replacement is then drawn straight over whatever survived.
- **Two accepted sentences share a line.** Each is drawn from its own start with
  its own wrapping, so they overlap.
- **A rotated page.** The relationship between extracted coordinates and drawing
  coordinates stops being the identity, and getting it subtly wrong produces
  garbled output rather than an error.
- **Characters the face cannot draw.** See below.

## What it cannot do

**Reflow.** A shorter rewrite leaves the line it no longer fills blank; a longer
one shrinks slightly rather than pushing the page down. Text below never moves,
because moving it means re-laying out a document we did not author.

**Match the font exactly.** Embedded fonts are *subsets* -- a LaTeX resume
carries `DGBDFT+CMR10`, holding only the glyphs that document already uses -- so
new words must be drawn in a stock face chosen to match the original's style,
weight and colour. Close, and visibly not identical under inspection.

**Draw outside Latin-1.** The stock faces are Latin-1. Typographic characters a
model reaches for -- em dashes, curly quotes, ellipses -- are folded to their
ASCII equivalents, and anything still outside Latin-1 refuses rather than
rendering as `?` in someone's resume.

**Keep justification.** A justified paragraph stretches word spacing to reach
both margins; a replacement is drawn with natural spacing and is therefore
ragged on the right inside it. Known, not currently corrected.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

#: Smallest we will shrink replacement text before giving up.
#:
#: Below this it stops matching the surrounding lines closely enough to pass as
#: the same document, which is the only reason to be editing in place at all.
_MIN_FONT_SIZE = 8.0

#: Stock faces, by style. The original's own font cannot be reused -- see the
#: module docstring. Keyed (serif, bold, italic).
_FACES = {
    (True, False, False): "tiro",
    (True, True, False): "tibo",
    (True, False, True): "tiit",
    (True, True, True): "tibi",
    (False, False, False): "helv",
    (False, True, False): "hebo",
    (False, False, True): "heit",
    (False, True, True): "hebi",
}

#: Substrings that mark an embedded font as serif. `CM` is Computer Modern,
#: which is what every LaTeX resume uses.
_SERIF_HINTS = ("CM", "Times", "Serif", "Roman", "Georgia", "Garamond", "Minion")

#: Span flag bits PyMuPDF sets for weight and slant.
_FLAG_ITALIC = 1 << 1
_FLAG_BOLD = 1 << 4

#: Typographic characters folded to what a Latin-1 face can draw.
#:
#: A model reaches for these constantly. Left alone they render as `?` in a
#: resume, which is worse than the plain equivalent.
_FOLD = {
    0x2014: "-",
    0x2013: "-",
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
    0x2026: "...",
    0x00A0: " ",
    0x2022: "•",  # bullet: Latin-1 has none, but it is in the fold table
}

#: Tolerance for "is this glyph past the end of the match", in points.
#:
#: A rectangle's right edge and the next glyph's left edge routinely differ by a
#: fraction, so an exact comparison reports neighbours that are not there.
_EDGE_TOLERANCE = 1.0


@dataclass(frozen=True, slots=True)
class EditResult:
    pdf: bytes
    applied: int
    #: Sentences that could not be placed, with the reason.
    skipped: tuple[tuple[str, str], ...]


class NotEditableError(ValueError):
    """The document cannot be edited in place at all.

    Distinct from "one sentence did not fit": this means the file is unusable
    for editing, and the caller should render a fresh document instead.
    """


@dataclass(frozen=True, slots=True)
class _Style:
    font: str
    size: float
    colour: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class _Slot:
    """One line of the original text, and exactly where it sat."""

    x: float
    #: The pen position the glyphs were drawn from. Drawing here is what makes
    #: the spacing the document's own.
    baseline: float
    right: float

    @property
    def width(self) -> float:
        return self.right - self.x


def _fold(text: str) -> str:
    """Fold typographic characters to what a Latin-1 face can draw."""
    return text.translate(_FOLD)


def _drawable(text: str) -> bool:
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True


def _lines_of(page_dict: dict) -> list[dict]:
    return [
        line
        for block in page_dict["blocks"]
        if not block.get("type")
        for line in block["lines"]
    ]


def _style_of(span: dict) -> _Style:
    name = span.get("font", "")
    flags = int(span.get("flags", 0))
    serif = any(hint.lower() in name.lower() for hint in _SERIF_HINTS)
    face = _FACES[(serif, bool(flags & _FLAG_BOLD), bool(flags & _FLAG_ITALIC))]
    return _Style(
        font=face,
        size=float(span.get("size", 10.0)),
        # Read rather than defaulted to black: a bolded blue heading redrawn in
        # plain black is wrong even on a perfect baseline.
        colour=pymupdf.sRGB_to_pdf(int(span.get("color", 0))),
    )


def _block_right(page_dict: dict, rect: pymupdf.Rect) -> float:
    """The paragraph's right edge, so a replacement may use the whole column."""
    for block in page_dict["blocks"]:
        if block.get("type"):
            continue
        outline = pymupdf.Rect(block["bbox"])
        if outline.contains(rect):
            return float(outline.x1)
    return float(rect.x1)


def _text_after(line: dict, rect: pymupdf.Rect) -> bool:
    """Is there text on this line past where the match ends?"""
    for span in line["spans"]:
        box = pymupdf.Rect(span["bbox"])
        if (
            span.get("text", "").strip()
            and box.x1 > rect.x1 + _EDGE_TOLERANCE
            and box.x0 >= rect.x1 - _EDGE_TOLERANCE
        ):
            return True
    return False


def _plan_lines(
    page_dict: dict, rects: list[pymupdf.Rect]
) -> tuple[list[_Slot], _Style] | None:
    """Where each matched line sat and how it was styled, or None to refuse."""
    lines = _lines_of(page_dict)
    slots: list[_Slot] = []
    style: _Style | None = None

    for index, rect in enumerate(rects):
        owner = next(
            (line for line in lines if pymupdf.Rect(line["bbox"]).intersects(rect)), None
        )
        if owner is None or not owner["spans"]:
            return None

        # Only the *last* line can have text after the match; an earlier one ends
        # because the sentence wrapped.
        if index == len(rects) - 1 and _text_after(owner, rect):
            return None

        span = min(
            owner["spans"],
            key=lambda candidate: abs(pymupdf.Rect(candidate["bbox"]).x0 - rect.x0),
        )
        if style is None:
            style = _style_of(span)

        slots.append(
            _Slot(
                x=float(rect.x0),
                baseline=float(span["origin"][1]),
                right=_block_right(page_dict, rect),
            )
        )

    return (slots, style) if style is not None else None


def _wrap(text: str, slots: list[_Slot], font: str, size: float) -> list[str] | None:
    """Greedy word wrap across the available lines, or None if it will not go.

    Each line has its own width: the first may start mid-way along, where the
    sentence began, while continuation lines start at their own indent.
    """
    words = text.split()
    if not words:
        return None

    out: list[str] = []
    index = 0
    for slot in slots:
        if slot.width <= 0:
            return None

        current = ""
        while index < len(words):
            candidate = f"{current} {words[index]}".strip()
            if pymupdf.get_text_length(candidate, fontname=font, fontsize=size) > slot.width:
                break
            current = candidate
            index += 1

        if not current and index < len(words):
            # One word too wide for the line it must start on. Without this the
            # loop cannot advance.
            return None
        out.append(current)

    # Anything left needs a line that does not exist. Refusing is the point: the
    # alternative is drawing over the row beneath.
    return None if index < len(words) else out


def _fit(text: str, slots: list[_Slot], style: _Style) -> tuple[list[str], float] | None:
    trial = style.size
    while trial >= _MIN_FONT_SIZE:
        wrapped = _wrap(text, slots, style.font, trial)
        if wrapped is not None:
            return wrapped, trial
        trial -= 0.5
    return None


def _occurrences(page: pymupdf.Page, needle: str) -> int:
    """How many times the sentence appears, ignoring how lines wrap."""
    flat = " ".join(page.get_text().split())
    target = " ".join(needle.split())
    return 0 if not target else flat.count(target)


def edit_pdf_in_place(pdf_bytes: bytes, replacements: list[tuple[str, str]]) -> EditResult:
    """Swap each `(original, suggested)` pair inside `pdf_bytes`."""
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - depends on the stored bytes
        raise NotEditableError(f"This file could not be opened as a PDF: {exc}") from exc

    if document.page_count == 0:
        raise NotEditableError("This PDF has no pages.")
    if any(page.rotation for page in document):
        # Extracted and drawing coordinates stop agreeing, and being subtly
        # wrong here produces garbled text rather than a clean failure.
        raise NotEditableError("Rotated pages cannot be edited in place.")

    # One extraction per page, reused. It is also the only copy of the geometry
    # that survives: `apply_redactions` rewrites the content stream, so every
    # measurement must happen before the first redaction.
    page_dicts = {page.number: page.get_text("dict") for page in document}

    planned: list[tuple[pymupdf.Page, list[pymupdf.Rect], list[_Slot], list[str], _Style, float]]
    planned = []
    skipped: list[tuple[str, str]] = []
    # Lines already claimed, as (page number, rounded baseline).
    claimed: set[tuple[int, int]] = set()

    for original, suggested in replacements:
        folded = _fold(suggested)
        if not _drawable(folded):
            skipped.append(
                (original, "the rewrite uses characters this document's font cannot show")
            )
            continue

        located = False
        for page in document:
            rects = page.search_for(original)
            if not rects:
                continue
            located = True

            if _occurrences(page, original) > 1:
                # Every match is redacted but only one is redrawn, so the others
                # would simply vanish from the resume.
                skipped.append((original, "that wording appears more than once in the document"))
                break

            geometry = _plan_lines(page_dicts[page.number], rects)
            if geometry is None:
                skipped.append(
                    (original, "other text shares those lines, so replacing it would damage them")
                )
                break

            slots, style = geometry
            keys = {(page.number, round(slot.baseline)) for slot in slots}
            if keys & claimed:
                # Two replacements on one line are drawn from their own starts
                # with their own wrapping, and overlap.
                skipped.append((original, "another change already applies to that line"))
                break

            fitted = _fit(folded, slots, style)
            if fitted is None:
                skipped.append((original, "the rewrite is too long for the space it would replace"))
                break

            wrapped, size = fitted
            claimed |= keys
            planned.append((page, rects, slots, wrapped, style, size))
            break

        if not located:
            # Usually because the sentence spans a column or page break, where
            # the extracted text reads continuously but the geometry does not.
            skipped.append((original, "that wording could not be located in the document"))

    for page, rects, _, _, _, _ in planned:
        for rect in rects:
            page.add_redact_annot(rect)

    for page in {entry[0] for entry in planned}:
        # Text only. The defaults also strip line art and images that merely
        # *touch* the rectangle, which would take the rule under a section
        # heading with them and leave the page looking broken in a way that has
        # nothing to do with the sentence being replaced.
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        )

    for page, _, slots, wrapped, style, size in planned:
        for slot, line in zip(slots, wrapped, strict=False):
            if not line:
                continue
            # One call per line, at the original pen position. Passing the lines
            # together would reintroduce PyMuPDF's own leading -- the bug this
            # module was rewritten to remove.
            page.insert_text(
                (slot.x, slot.baseline),
                line,
                fontname=style.font,
                fontsize=size,
                color=style.colour,
            )

    return EditResult(pdf=document.tobytes(), applied=len(planned), skipped=tuple(skipped))
