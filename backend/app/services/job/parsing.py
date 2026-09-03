"""Structured field extraction from a job description (US-3.1 AC2).

Pure functions, no database, mirroring `services/resume/contact.py` in shape and
in principle: **returning None is always the correct outcome when unsure.**
ADR-012 forbids the system inventing things about a candidate, and the same rule
applies to a posting — a guessed salary or a guessed seniority silently distorts
every match score computed against this row, and nobody can see that it was a
guess.

Weighted towards Indian postings alongside US and European ones, because that is
where this project's users are: LPA, lakh and crore notation, ₹ and Rs, and
B.Tech / MCA degree names are all first-class here rather than afterthoughts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    SalaryPeriod,
    WorkMode,
)

# How far into the text a "Label: value" header is still believable. Beyond
# this, "Location:" is usually part of a boilerplate footer about the company's
# offices rather than the role's location.
_HEADER_CHARS = 1500


def _labelled(text: str, labels: tuple[str, ...], *, within: int = _HEADER_CHARS) -> str | None:
    """Find `Label: value` on a single line.

    Values are capped at 120 characters and rejected if they span a sentence —
    a colon in prose ("Note: we are hiring across many teams and locations")
    would otherwise be read as a labelled field.
    """
    pattern = re.compile(
        rf"^[\s#*_>\-]*(?:{'|'.join(labels)})\s*[:\-\u2013]\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text[:within])
    if match is None:
        return None
    value = match.group(1).strip(" .;,*_-")
    if not value or len(value) > 120:
        return None
    return value


# ------------------------------------------------------------------ title


_TITLE_LABELS = ("job\\s*title", "position", "role", "designation", "title")


def find_title(text: str) -> str | None:
    """The role's title.

    A labelled header wins. Otherwise the first non-empty line, which is where
    almost every posting puts it — but only if it looks like a title rather than
    a sentence, because a description that opens with a paragraph would
    otherwise name the role after its first clause.
    """
    labelled = _labelled(text, _TITLE_LABELS)
    if labelled is not None:
        return labelled

    for line in text.splitlines()[:5]:
        candidate = line.strip(" #*_->•").strip()
        if not candidate:
            continue
        words = candidate.split()
        # A title is short, is not a sentence, and is not a bare company blurb.
        if (
            2 <= len(words) <= 12
            and len(candidate) <= 120
            and not candidate.endswith((".", "!", "?"))
            and "@" not in candidate
            and not candidate.lower().startswith(("about ", "we are", "we're", "our "))
        ):
            return candidate
        # Only the first non-empty line is considered. If that one is prose, the
        # posting does not lead with its title and guessing further down finds
        # section headings instead.
        return None

    return None


# ------------------------------------------------------------------ company


_COMPANY_LABELS = ("company", "employer", "organisation", "organization", "hiring\\s*company")
# "at Acme", "with Acme" — but only in the opening line, where it is part of the
# title. Deeper in the text it is far more likely to be prose.
_COMPANY_INLINE = re.compile(
    r"\b(?:at|with|for)\s+([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,3})\s*$"
)

# "Acme Technologies Pvt Ltd builds payments infrastructure..." — the opening
# sentence of an About section. A proper-noun run followed by one of a closed
# list of verbs, which is what distinguishes a company name from any other
# capitalised phrase.
_COMPANY_SENTENCE = re.compile(
    r"^([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4})\s+"
    r"(?:is|are|was|builds?|provides?|helps?|makes?|offers?|operates?|powers?|"
    r"delivers?|develops?|creates?|serves?)\b",
    re.MULTILINE,
)

# Openers that pass the capitalisation test but name no company. Without this,
# "We are a small team" yields a company called "We" — and every posting that
# opens that way collapses into one employer.
_NOT_A_COMPANY = frozenset(
    {
        "we",
        "our",
        "the",
        "this",
        "that",
        "you",
        "it",
        "they",
        "here",
        "there",
        "as",
        "join",
        "about",
        "who",
        "what",
        "your",
        "their",
        "his",
        "her",
        "i",
    }
)


def find_company(text: str) -> str | None:
    """The employer.

    Three routes, most reliable first. A wrong company is worse than none: it
    merges two employers' postings under one row, which corrupts the "same
    company" scoping that near-duplicate detection depends on.
    """
    labelled = _labelled(text, _COMPANY_LABELS)
    if labelled is not None:
        return labelled

    for line in text.splitlines()[:3]:
        stripped = line.strip(" #*_->•").strip()
        if not stripped or len(stripped) > 120:
            continue
        match = _COMPANY_INLINE.search(stripped)
        if match is not None:
            return match.group(1).strip()

    for match in _COMPANY_SENTENCE.finditer(text[:_HEADER_CHARS]):
        candidate = match.group(1).strip()
        if candidate.split()[0].lower() not in _NOT_A_COMPANY:
            return candidate

    return None


# ------------------------------------------------------------------ location


_LOCATION_LABELS = ("location", "job\\s*location", "work\\s*location", "based\\s*in", "city")


def find_location(text: str) -> str | None:
    """Where the job is.

    Returned verbatim, exactly as `contact.py` does for a resume. Normalising
    "Bengaluru, KA, India" to a canonical city needs a gazetteer this project
    does not have, and a wrong normalisation distorts the location dimension of
    the ranking formula.
    """
    labelled = _labelled(text, _LOCATION_LABELS)
    if labelled is None:
        return None
    # Strip a trailing work-mode annotation — "Bengaluru (Remote)" — which is
    # captured separately and is not part of the place name.
    cleaned = re.sub(
        r"[\(\[]?\s*(remote|hybrid|on-?site|wfh|work from home)\s*[\)\]]?\s*$",
        "",
        labelled,
        flags=re.IGNORECASE,
    ).strip(" ,-\u2013|")
    return cleaned or None


# ------------------------------------------------------------------ work mode


_REMOTE = re.compile(
    r"\b(fully\s+remote|100%\s+remote|remote[\s-]first|work\s+from\s+home|wfh|remote)\b",
    re.IGNORECASE,
)
_HYBRID = re.compile(
    r"\b(hybrid|\d\s*days?\s+(?:a|per)\s+week\s+in\s+(?:the\s+)?office)\b", re.IGNORECASE
)
_ONSITE = re.compile(
    r"\b(on-?site|in-?office|in\s+person|work\s+from\s+office|wfo)\b", re.IGNORECASE
)


def find_work_mode(text: str) -> WorkMode | None:
    """Remote, hybrid or onsite.

    Hybrid is checked first and wins outright: "hybrid — 3 days remote" contains
    the word remote, and a hybrid role classified as REMOTE scores a candidate
    who cannot relocate far too highly.
    """
    if _HYBRID.search(text):
        return WorkMode.HYBRID
    if _REMOTE.search(text):
        return WorkMode.REMOTE
    if _ONSITE.search(text):
        return WorkMode.ONSITE
    return None


# ------------------------------------------------------------------ employment type


_EMPLOYMENT_PATTERNS: tuple[tuple[EmploymentType, re.Pattern[str]], ...] = (
    (EmploymentType.INTERNSHIP, re.compile(r"\b(internship|intern|trainee|apprentice)\b", re.I)),
    (
        EmploymentType.CONTRACT,
        re.compile(r"\b(contract|contractor|freelance|consultant|c2h)\b", re.I),
    ),
    (EmploymentType.PART_TIME, re.compile(r"\bpart[\s-]?time\b", re.I)),
    (EmploymentType.TEMPORARY, re.compile(r"\b(temporary|temp|seasonal|fixed[\s-]term)\b", re.I)),
    (EmploymentType.FULL_TIME, re.compile(r"\bfull[\s-]?time\b", re.I)),
)


def find_employment_type(text: str) -> EmploymentType | None:
    """Ordered most-specific first.

    An internship posting says "full-time internship", so checking FULL_TIME
    first would classify every intern role as a permanent one.
    """
    for employment_type, pattern in _EMPLOYMENT_PATTERNS:
        if pattern.search(text):
            return employment_type
    return None


# ------------------------------------------------------------------ experience


# "3-5 years", "3 to 5 years", "5+ years", "minimum of 2 years", "at least 4 yrs"
_YEARS_RANGE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_YEARS_MIN = re.compile(
    r"(?:(?:minimum|min|at\s+least|over|more\s+than)\s+(?:of\s+)?)?(\d{1,2})\s*(?:\+|plus)\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_YEARS_AT_LEAST = re.compile(
    r"(?:minimum|min|at\s+least)\s+(?:of\s+)?(\d{1,2})\s*(?:years?|yrs?)\b", re.IGNORECASE
)

_MAX_PLAUSIBLE_YEARS = 40


@dataclass(frozen=True, slots=True)
class ExperienceRange:
    min_years: Decimal | None
    max_years: Decimal | None


def find_experience_range(text: str) -> ExperienceRange | None:
    """Years of experience asked for.

    A bare "5 years" with no qualifier is deliberately not matched. It appears
    constantly in prose that is not a requirement — "five years ago we started",
    "5 years of double-digit growth" — and a wrong minimum silently penalises
    every candidate below it.
    """
    range_match = _YEARS_RANGE.search(text)
    if range_match is not None:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        if 0 <= low <= high <= _MAX_PLAUSIBLE_YEARS:
            return ExperienceRange(Decimal(low), Decimal(high))

    for pattern in (_YEARS_MIN, _YEARS_AT_LEAST):
        match = pattern.search(text)
        if match is not None:
            low = int(match.group(1))
            if 0 <= low <= _MAX_PLAUSIBLE_YEARS:
                return ExperienceRange(Decimal(low), None)

    return None


_LEVEL_PATTERNS: tuple[tuple[ExperienceLevel, re.Pattern[str]], ...] = (
    (ExperienceLevel.INTERN, re.compile(r"\b(intern|internship|trainee)\b", re.I)),
    (ExperienceLevel.PRINCIPAL, re.compile(r"\bprincipal\b", re.I)),
    (ExperienceLevel.LEAD, re.compile(r"\b(lead|staff|architect|head\s+of)\b", re.I)),
    (
        ExperienceLevel.SENIOR,
        re.compile(r"\b(senior|sr\.?|sde\s*(?:ii|iii|3)|experienced)\b", re.I),
    ),
    (ExperienceLevel.JUNIOR, re.compile(r"\b(junior|jr\.?|associate)\b", re.I)),
    (
        ExperienceLevel.ENTRY,
        re.compile(r"\b(entry[\s-]level|fresher|graduate|campus\s+hire|new\s+grad)\b", re.I),
    ),
)


def find_experience_level(title: str | None, text: str) -> ExperienceLevel | None:
    """Seniority, from the title first and the body second.

    The title is the reliable signal. A body mentioning "you will mentor junior
    engineers" describes the team, not the role, so the body is consulted only
    when the title says nothing.
    """
    for source in (title or "", text[:_HEADER_CHARS]):
        for level, pattern in _LEVEL_PATTERNS:
            if pattern.search(source):
                return level
    return None


# ------------------------------------------------------------------ education


_EDUCATION_PATTERNS: tuple[tuple[EducationLevel, re.Pattern[str]], ...] = (
    (
        EducationLevel.HIGH_SCHOOL,
        re.compile(r"\b(high\s+school|higher\s+secondary|12th|hsc)\b", re.I),
    ),
    (EducationLevel.DIPLOMA, re.compile(r"\bdiploma\b", re.I)),
    (
        EducationLevel.BACHELORS,
        re.compile(
            r"\b(bachelor'?s?|b\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc|b\.?\s?c\.?a|b\.?\s?s\b|undergraduate|"
            r"engineering\s+degree)\b",
            re.I,
        ),
    ),
    (
        EducationLevel.MASTERS,
        re.compile(
            r"\b(master'?s?|m\.?\s?tech|m\.?\s?sc|m\.?\s?c\.?a|m\.?\s?b\.?a|m\.?\s?s\b"
            r"|post\s*graduate)\b",
            re.I,
        ),
    ),
    (EducationLevel.DOCTORATE, re.compile(r"\b(ph\.?\s?d|doctorate|doctoral)\b", re.I)),
)


def find_min_education(text: str) -> EducationLevel | None:
    """The lowest degree level the posting names.

    Lowest, not highest, because the column is a *minimum*: "Bachelor's required,
    Master's preferred" asks for a bachelor's. The known imprecision is a posting
    that names only a higher degree as preferred — "Master's a plus" alone reads
    as a Master's minimum. Accepted because the alternative, reading requirement
    wording, is guesswork of a worse kind, and the education dimension is 10% of
    the score (ml.md section 4.1).
    """
    found = [level for level, pattern in _EDUCATION_PATTERNS if pattern.search(text)]
    return min(found, key=lambda level: level.rank) if found else None


# ------------------------------------------------------------------ salary


_CURRENCY_SIGNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("INR", re.compile(r"₹|\bINR\b|\bRs\.?\b|\brupees?\b|\bLPA\b|\blakhs?\b|\bcrores?\b", re.I)),
    ("USD", re.compile(r"\$|\bUSD\b|\bdollars?\b", re.I)),
    ("EUR", re.compile(r"€|\bEUR\b|\beuros?\b", re.I)),
    ("GBP", re.compile(r"£|\bGBP\b|\bpounds?\b", re.I)),
    ("AED", re.compile(r"\bAED\b|\bdirhams?\b", re.I)),
    ("SGD", re.compile(r"\bSGD\b", re.I)),
    ("CAD", re.compile(r"\bCAD\b", re.I)),
    ("AUD", re.compile(r"\bAUD\b", re.I)),
)

_PERIOD_PATTERNS: tuple[tuple[SalaryPeriod, re.Pattern[str]], ...] = (
    (SalaryPeriod.HOURLY, re.compile(r"\b(per\s+hour|hourly|/\s*hr|/\s*hour|an\s+hour)\b", re.I)),
    (
        SalaryPeriod.MONTHLY,
        re.compile(r"\b(per\s+month|monthly|/\s*month|/\s*mo|a\s+month|p\.?m\.?)\b", re.I),
    ),
    (
        SalaryPeriod.YEARLY,
        re.compile(
            r"\b(per\s+annum|per\s+year|annually|yearly|/\s*year|/\s*yr|a\s+year"
            r"|p\.?a\.?|LPA|CTC)\b",
            re.I,
        ),
    ),
)

# A number with optional thousands separators (Western 1,200,000 or Indian
# 12,00,000) and an optional magnitude suffix.
#
# The suffix alternatives are ordered longest-first — lpa before lakh before l —
# because the regex alternation is first-match, and a bare `l` would otherwise
# consume the L of LPA and leave "PA" behind.
#
# `(?![a-zA-Z])` is what stops "10 members" parsing as 10 million: the `m`
# alternative only counts when no letter follows it. It is also why `lpa` needs
# its own alternative rather than falling out of `l`.
_MAGNITUDE_SUFFIX = r"(?:k|lpa|lakhs?|lacs?|l|crores?|cr|mn|m)"
_AMOUNT = rf"\d{{1,3}}(?:[,\d]{{0,12}})?(?:\.\d+)?\s*{_MAGNITUDE_SUFFIX}?(?![a-zA-Z])"
# The currency marker is usually repeated on the second figure — "₹12,00,000 -
# ₹18,00,000", "$120k - $150k" — so the separator has to allow one, or the
# range never matches and every such posting loses its salary.
_SALARY_RANGE = re.compile(
    rf"({_AMOUNT})\s*(?:-|\u2013|\u2014|to|and)\s*(?:[₹$€£]|Rs\.?|INR|USD|EUR|GBP)?\s*({_AMOUNT})",
    re.IGNORECASE,
)

_MAGNITUDES: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"^(?:cr|crores?)$", re.I), 10_000_000),
    # LPA is "lakhs per annum" — the magnitude and the period in one token. The
    # period half is picked up separately by _PERIOD_PATTERNS.
    (re.compile(r"^(?:lpa|l|lakhs?|lacs?)$", re.I), 100_000),
    (re.compile(r"^(?:m|mn)$", re.I), 1_000_000),
    (re.compile(r"^k$", re.I), 1_000),
)


def _magnitude_of(raw: str) -> int | None:
    """The multiplier a written amount carries, if any."""
    match = re.search(rf"({_MAGNITUDE_SUFFIX})\s*$", raw.strip(), re.IGNORECASE)
    if match is None:
        return None
    for pattern, value in _MAGNITUDES:
        if pattern.match(match.group(1)):
            return value
    return None

# Below this, a "salary" is a typo, a headcount or a year. Above it, it is a
# revenue figure from the company blurb.
_MIN_PLAUSIBLE_SALARY = Decimal(1000)
_MAX_PLAUSIBLE_SALARY = Decimal(100_000_000)


@dataclass(frozen=True, slots=True)
class SalaryRange:
    minimum: Decimal | None
    maximum: Decimal | None
    currency: str | None
    period: SalaryPeriod | None


def _to_amount(raw: str) -> Decimal | None:
    """Parse "12,00,000", "15L", "120k" or "1.2 cr" into a number."""
    text = raw.strip()
    multiplier = _magnitude_of(text) or 1
    suffix_match = re.search(rf"{_MAGNITUDE_SUFFIX}\s*$", text, re.IGNORECASE)
    if suffix_match is not None:
        text = text[: suffix_match.start()]

    digits = text.replace(",", "").strip()
    if not digits or not re.fullmatch(r"\d+(?:\.\d+)?", digits):
        return None
    try:
        return Decimal(digits) * multiplier
    except ArithmeticError:
        return None


def find_salary(text: str) -> SalaryRange | None:
    """A pay range, if the posting states one.

    Requires a currency indicator somewhere near the numbers. Without that guard
    every "3 - 5 years" and "10 to 20 people" in a description parses as pay, and
    a fabricated salary range is worse than no salary at all — the ranking
    formula treats a missing salary as neutral (0.5) but scores a stated one.
    """
    for currency, sign in _CURRENCY_SIGNS:
        for sign_match in sign.finditer(text):
            # Look in a window around the currency marker rather than the whole
            # document, so a "$" in the benefits section cannot lend credibility
            # to a number in the requirements.
            window_start = max(0, sign_match.start() - 60)
            window = text[window_start : sign_match.end() + 80]

            range_match = _SALARY_RANGE.search(window)
            if range_match is None:
                continue

            low_raw, high_raw = range_match.group(1), range_match.group(2)
            low = _to_amount(low_raw)
            high = _to_amount(high_raw)
            if low is None or high is None:
                continue

            # "12 - 18 LPA" and "$120 - 150k" write the magnitude once, after
            # the second number. Without carrying it back, the low end parses as
            # 12 against a high of 1,800,000 and the range is nonsense.
            carried = _magnitude_of(high_raw)
            if carried is not None and _magnitude_of(low_raw) is None:
                low = low * carried

            if low > high:
                low, high = high, low

            if not (_MIN_PLAUSIBLE_SALARY <= low <= high <= _MAX_PLAUSIBLE_SALARY):
                continue

            period = next(
                (p for p, pattern in _PERIOD_PATTERNS if pattern.search(window)),
                None,
            )
            return SalaryRange(low, high, currency, period)

    return None
