"""Read a model's reply strictly, or not at all (ml.md section 6.2).

Output schema validation is the layer that rejects anything off-shape. The rule
here is that a malformed reply produces *nothing*, never a partial object with
plausible defaults -- a suggestion whose `original` was quietly defaulted to ""
would be applied against the wrong part of a resume.

## Fences

Models wrap JSON in ```json fences constantly, whatever the instruction says.
Stripping them is not leniency about the schema, it is accepting a well-known
presentation habit; the JSON inside is still parsed strictly. Anything past that
-- a missing field, a wrong type, prose around the object -- is a rejection.

## Partial results are kept

One malformed entry does not discard the batch. The others are independently
valid and independently useful, and throwing away seven good suggestions because
the eighth lost a field would be a worse answer, not a safer one. The count of
dropped entries is returned so the loss is visible rather than silent -- the same
reasoning as `rejected_by_validator`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

#: ```json ... ``` or ``` ... ```, anywhere in the reply.
_FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

#: Fields a suggestion cannot be useful without.
_REQUIRED = ("original", "suggested")

#: Longest text accepted in any single field.
#:
#: A resume bullet is a sentence or two. Something far longer is a model that has
#: started writing an essay or echoing its input, and storing it would put an
#: unbounded string in a column and in front of a reviewer.
_MAX_FIELD = 2_000

#: More than this and the model has ignored the instruction to be selective.
_MAX_SUGGESTIONS = 8


@dataclass(frozen=True, slots=True)
class RawSuggestion:
    """One suggestion as the model returned it, shape-checked and nothing more.

    Deliberately *not* validated for truthfulness here. Whether the rewrite
    invents anything is the fabrication validator's question, and answering it in
    two places would mean two answers.
    """

    original: str
    suggested: str
    section: str = ""
    rationale: str = ""
    grounded_in: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParseResult:
    suggestions: tuple[RawSuggestion, ...]
    #: Entries that were the right general shape but failed the field checks.
    dropped: int = 0


class ResponseFormatError(ValueError):
    """The reply was not usable at all -- not JSON, or not the expected object."""


def _unfence(text: str) -> str:
    match = _FENCED.search(text)
    return match.group(1).strip() if match else text.strip()


def _clean(value: object) -> str | None:
    """A non-empty string within length, or None.

    `None` rather than "" so a caller cannot mistake a missing field for an empty
    one, which is the mistake that would apply a suggestion to nothing.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_FIELD:
        return None
    return stripped


def parse_suggestions(reply: str) -> ParseResult:
    """Read the model's reply into suggestions.

    Raises `ResponseFormatError` when nothing usable can be read. Returns an
    empty list when the model correctly said it had no suggestions -- those are
    different outcomes and a caller treats them differently: the first is a
    defect worth logging, the second is a valid answer.
    """
    try:
        payload = json.loads(_unfence(reply))
    except (ValueError, TypeError) as exc:
        raise ResponseFormatError("reply was not JSON") from exc

    if not isinstance(payload, dict):
        raise ResponseFormatError(f"expected a JSON object, got {type(payload).__name__}")

    entries = payload.get("suggestions")
    if entries is None:
        raise ResponseFormatError("reply had no 'suggestions' key")
    if not isinstance(entries, list):
        raise ResponseFormatError("'suggestions' was not a list")

    kept: list[RawSuggestion] = []
    dropped = 0

    for entry in entries[:_MAX_SUGGESTIONS]:
        if not isinstance(entry, dict):
            dropped += 1
            continue

        fields = {name: _clean(entry.get(name)) for name in _REQUIRED}
        if any(value is None for value in fields.values()):
            dropped += 1
            continue

        # A rewrite identical to its source is not a suggestion. Offering one
        # asks a reviewer to make a decision with no difference in it.
        if fields["original"] == fields["suggested"]:
            dropped += 1
            continue

        grounded = entry.get("grounded_in")
        sources: tuple[str, ...] = ()
        if isinstance(grounded, list):
            sources = tuple(
                cleaned for raw in grounded if (cleaned := _clean(raw)) is not None
            )

        kept.append(
            RawSuggestion(
                original=fields["original"],  # type: ignore[arg-type]
                suggested=fields["suggested"],  # type: ignore[arg-type]
                section=_clean(entry.get("section")) or "",
                rationale=_clean(entry.get("rationale")) or "",
                grounded_in=sources,
            )
        )

    dropped += max(0, len(entries) - _MAX_SUGGESTIONS)
    return ParseResult(suggestions=tuple(kept), dropped=dropped)
