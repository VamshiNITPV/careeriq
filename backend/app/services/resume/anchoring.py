"""Find the span of resume text a suggestion claims to be rewriting.

A suggestion carries the text it replaces. Matching that back to the resume is
not the trivial `in` check it looks like, for two reasons found the first time
this ran against a real document:

1. **Extracted text wraps.** A PDF sentence arrives as
   `"efficiently\\n        deployed on Vercel"`. The model writes it back on one
   line. Those are the same sentence and a literal comparison says otherwise.

2. **Models do not copy exactly.** Asked to reproduce a line character for
   character, a model will still merge two bullets, drop a clause, or smooth the
   wording. That is not a formatting difference and must not be treated as one.

So whitespace is flexible and **words are not**. Every word must be present, in
order, separated only by whitespace. A suggestion that fails this is not
anchored to the resume, and the honest response is to drop it rather than guess
where it belongs -- putting a rewrite in the wrong place edits a sentence the
user never chose to change.

Deliberately not fuzzy matching. "Close enough" here means replacing text
nobody approved, which is the failure this whole feature is built to avoid.
"""

from __future__ import annotations

import re


def find_span(text: str, original: str) -> tuple[int, int] | None:
    """Where `original` sits in `text`, tolerating only whitespace differences.

    Returns the first match as `(start, end)` offsets into `text`, or None when
    the words are not all there in order.
    """
    words = original.split()
    if not words:
        return None

    # `\s+` between words, so a line break, a run of spaces and a single space
    # are all the same separator. The words themselves are escaped, so
    # punctuation and regex characters in a resume are matched literally.
    pattern = r"\s+".join(re.escape(word) for word in words)
    match = re.search(pattern, text)
    return None if match is None else (match.start(), match.end())


def replace_span(text: str, original: str, replacement: str) -> str | None:
    """Swap the first occurrence of `original` for `replacement`.

    None when there is nothing to replace, so a caller cannot mistake "no change
    was needed" for "the text was not found".
    """
    span = find_span(text, original)
    if span is None:
        return None
    start, end = span
    return text[:start] + replacement + text[end:]
