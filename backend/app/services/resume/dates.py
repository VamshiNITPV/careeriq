"""Date-range parsing for resume entries.

Resumes write dates a dozen ways - "Jan 2020 - Present", "2019-2023",
"03/2021 to 06/2022", "Since May 2021". This turns them into comparable values.

Everything is **month precision**, with the day forced to 1. A resume that says
"Jan 2020" does not know which day, and storing the 1st as if it were a fact
would be precision the source never had. Callers that render these must not show
a day.

Precision over recall, as everywhere else in extraction: an unparseable range
returns nothing rather than a guess. A wrong start date silently changes the
years-of-experience figure the ranking formula reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

_MONTHS: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}  # fmt: skip

# Words meaning "this has not ended". "Till date" and "presently" are common in
# Indian resumes; "ongoing" turns up on projects.
_CURRENT = re.compile(
    r"\b(present|current(?:ly)?|now|to\s*date|till\s*date|ongoing|date)\b", re.IGNORECASE
)

# Longest first, so "september" is matched before "sep" leaves "tember" behind.
# Exported because entity extraction has to strip the same vocabulary, and two
# copies would drift.
MONTH_NAME_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_NAMES = MONTH_NAME_PATTERN

# "Jan 2020", "January, 2020"
_MONTH_YEAR = re.compile(rf"\b({_MONTH_NAMES})\.?,?\s+((?:19|20)\d{{2}})\b", re.IGNORECASE)
# "03/2021", "3-2021"
_NUMERIC_MONTH_YEAR = re.compile(r"\b(0?[1-9]|1[0-2])[/\-.]((?:19|20)\d{2})\b")
# "2019" on its own.
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")

# What separates the two ends of a range. Written as escapes because an en dash
# is indistinguishable from a hyphen in source (see skill_extraction.py).
_SEPARATOR = r"(?:\s*(?:-|\u2013|\u2014|to|until|through|\u2014)\s*)"

_MIN_YEAR = 1950
# Some head-room: a graduation date can legitimately be in the future.
_MAX_YEAR_AHEAD = 10


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date | None
    end: date | None
    is_current: bool

    @property
    def is_empty(self) -> bool:
        return self.start is None and self.end is None and not self.is_current


def _plausible(year: int) -> bool:
    return _MIN_YEAR <= year <= datetime.now(UTC).year + _MAX_YEAR_AHEAD


def _at(year: int, month: int) -> date | None:
    if not _plausible(year) or not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def _parse_one(text: str) -> date | None:
    """The first date in a fragment, at month precision."""
    month_year = _MONTH_YEAR.search(text)
    if month_year is not None:
        return _at(int(month_year.group(2)), _MONTHS[month_year.group(1).lower()])

    numeric = _NUMERIC_MONTH_YEAR.search(text)
    if numeric is not None:
        return _at(int(numeric.group(2)), int(numeric.group(1)))

    year = _YEAR.search(text)
    if year is not None:
        # No month stated, so January — and the caller knows only the year is
        # meaningful because that is all the resume said.
        return _at(int(year.group(1)), 1)

    return None


def find_date_range(text: str) -> DateRange:
    """Pull a start and end out of a line.

    Returns an empty range rather than raising: most lines in a resume contain
    no dates at all, and that is not an error.
    """
    stripped = text.strip()
    if not stripped:
        return DateRange(None, None, False)

    is_current = _CURRENT.search(stripped) is not None

    # Split on the separator and read each side, rather than one regex with two
    # capture groups: the two ends are often written in different formats —
    # "Jan 2020 - 2023" is ordinary.
    parts = re.split(_SEPARATOR, stripped, maxsplit=1, flags=re.IGNORECASE)

    if len(parts) == 2:
        start = _parse_one(parts[0])
        end = None if is_current else _parse_one(parts[1])
        # A trailing "Present" leaves the second part with no date, which is
        # exactly what is_current means. But "2020 - 2023" where the second
        # half failed to parse should not silently become open-ended.
        if start is not None or end is not None:
            if start is not None and end is not None and end < start:
                # Written the other way round, or one end misread. Swapping is
                # the only interpretation that yields a coherent range.
                start, end = end, start
            return DateRange(start, end, is_current and end is None)

    single = _parse_one(stripped)
    if single is not None:
        # One date and a "present" marker is an open range starting then;
        # one date alone is a point, which for an entry means it started then.
        return DateRange(single, None, is_current)

    return DateRange(None, None, is_current)


def has_date_range(text: str) -> bool:
    """Whether a line carries dates at all — used to find entry boundaries."""
    return not find_date_range(text).is_empty


def format_month(value: date | None) -> str | None:
    """ "2020-01" — the precision actually held, for a content key."""
    return None if value is None else f"{value.year:04d}-{value.month:02d}"
