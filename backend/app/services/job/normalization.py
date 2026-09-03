"""Normalisation for job text, titles, company names and the dedup hash.

Pure functions, no database. These decide identity: two postings are the same
company when their normalised names match, and the same posting when their
hashes match. Getting them wrong either splits one employer into five rows or
merges two real companies into one, so each rule is narrow and deliberate.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Legal suffixes stripped when deciding whether two company names are the same
# employer. "Acme, Inc." and "Acme" are; "Acme Health" and "Acme Motors" are not,
# which is why only this closed list is removed and no other trailing word is.
_LEGAL_SUFFIXES = (
    "incorporated",
    "corporation",
    "limited",
    "holdings",
    "group",
    "gmbh",
    "pvt ltd",
    "private limited",
    "llp",
    "llc",
    "plc",
    "inc",
    "corp",
    "ltd",
    "co",
    "sa",
    "ag",
    "bv",
    "nv",
    "oy",
    "ab",
    "as",
    "srl",
    "spa",
    "pte",
    "pty",
)

# Longest first. The list contains both "limited" and "private limited", and
# checking in declaration order strips the shorter one, leaving "zeta labs
# private" — a key that matches nothing else.
_LEGAL_SUFFIXES_BY_LENGTH = tuple(sorted(_LEGAL_SUFFIXES, key=len, reverse=True))

# Seniority and req-number noise removed from a title before grouping. The title
# itself is kept verbatim on the row; this is only the grouping key.
_TITLE_NOISE = re.compile(
    r"""
    \b(
        sr | snr | senior | jr | junior | lead | principal | staff | chief |
        head | associate | assistant | entry[\s-]level | mid[\s-]level |
        i{1,3} | iv | v{1,3} | ix | x
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# "(Remote)", "[Req 12345]", "- Bangalore" trailing decorations.
_TITLE_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_REQ_NUMBER = re.compile(r"\b(req(uisition)?|job|posting)?\s*#?\s*\d{3,}\b", re.IGNORECASE)


def _fold(value: str) -> str:
    """Lowercase, strip diacritics, collapse punctuation to single spaces."""
    folded = unicodedata.normalize("NFD", value)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.lower()
    # Periods are deleted rather than replaced with a space, which is what makes
    # an abbreviation survive: "S.A." has to become "sa" to match "SA", and
    # "Inc." has to become "inc" for the suffix list to see it. Replacing with a
    # space would give "s a" and "inc ", and neither matches anything.
    folded = folded.replace(".", "")
    # `+` and `#` are kept so "C++ Developer" and "C# Developer" stay distinct
    # titles rather than collapsing into "c developer".
    folded = re.sub(r"[^a-z0-9+#]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def normalize_company_name(name: str) -> str:
    """Dedup key for an employer.

    Suffixes are stripped repeatedly, because "Acme Technologies Pvt Ltd" ends in
    two of them. Stripping stops if it would empty the string — a company
    genuinely called "Group" keeps its name rather than becoming a row with an
    empty key that every other empty key collides with.
    """
    folded = _fold(name)
    if not folded:
        return ""

    changed = True
    while changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES_BY_LENGTH:
            if folded.endswith(f" {suffix}"):
                candidate = folded[: -len(suffix) - 1].strip()
                if candidate:
                    folded = candidate
                    changed = True
                    break

    return folded


def normalize_title(title: str) -> str:
    """Grouping key for a job title.

    "Sr. Software Engineer II (Remote)" and "Software Engineer" both become
    "software engineer", so analytics can count them together and near-duplicate
    detection has a trigram target that is not dominated by seniority words.

    Returns the folded title unchanged if stripping would empty it — "Senior"
    alone as a title is nonsense, but returning "" would make it collide with
    every other unparseable title.
    """
    without_brackets = _TITLE_BRACKETS.sub(" ", title)
    without_req = _REQ_NUMBER.sub(" ", without_brackets)
    folded = _fold(without_req)
    if not folded:
        return ""

    stripped = _TITLE_NOISE.sub(" ", folded)
    # The escapes are en and em dashes, written that way for the reason
    # skill_extraction.py gives: they are visually indistinguishable
    # from a hyphen in source, so the escape is what makes the intent readable.
    stripped = re.sub(r"\s+", " ", stripped).strip(" -\u2013\u2014/,")
    return stripped or folded


def clean_description(text: str) -> str:
    """Normalise a description for hashing and, later, embedding.

    Collapses whitespace and strips zero-width characters, so the same posting
    copied from two sites hashes identically. Deliberately does NOT lowercase or
    remove punctuation: `description_clean` is also what gets embedded in Phase
    6, and case and sentence structure carry meaning to a sentence transformer.
    """
    without_invisibles = re.sub(r"[\u200b-\u200f\u2028\u2029\ufeff]", "", text)
    # Normalise the unicode dashes and quotes that differ between sites but not
    # in meaning, so a copy-paste from two sources still hashes the same.
    translated = without_invisibles.translate(
        str.maketrans(
            {
                "\u2018": "'",
                "\u2019": "'",
                "\u201c": '"',
                "\u201d": '"',
                "\u2013": "-",
                "\u2014": "-",
            }
        )
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in translated.splitlines()]
    # Drop runs of blank lines but keep single ones: paragraph breaks are what
    # section detection reads.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def content_hash(clean_text: str) -> str:
    """Stage one of duplicate detection (US-3.2 AC1).

    Hashes a case-folded, whitespace-free form rather than `description_clean`
    itself, so a re-post that differs only in capitalisation or line wrapping is
    still caught by the cheap index lookup instead of falling through to the
    embedding comparison.
    """
    squeezed = re.sub(r"\s+", "", clean_text).lower()
    return hashlib.sha256(squeezed.encode("utf-8")).hexdigest()
