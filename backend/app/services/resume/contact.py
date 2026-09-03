"""Contact detail extraction from a resume header (US-2.3 AC1).

Pure functions, no database and no framework — same shape as sections.py, and
unit-testable without either.

The governing rule is that **returning None is always an acceptable answer**.
These values are written into a real person's profile, so a wrong guess is worse
than a blank: "Curriculum Vitae" in the name field is embarrassing and
untraceable, whereas an empty field is obviously empty and takes one keystroke
to fix. Every heuristic below is therefore biased toward rejecting.

Order matters. Emails and URLs are matched first and the lines carrying them are
masked, because nearly every false positive in name and location detection comes
from a contact line being mistaken for something else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# How much of the document to consider when no CONTACT section was detected.
HEAD_LINES = 15


@dataclass(frozen=True, slots=True)
class ContactDetails:
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_LINKEDIN = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/([A-Za-z0-9_%-]+)/?",
    re.IGNORECASE,
)

# Only the first path segment is captured: a resume often links a repository,
# and github.com/priya/careeriq identifies the person as "priya".
_GITHUB = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)",
    re.IGNORECASE,
)

# GitHub paths that are site features rather than usernames.
_GITHUB_RESERVED = frozenset(
    {"features", "about", "orgs", "topics", "sponsors", "pricing", "explore", "settings", "login"}
)

_GENERIC_URL = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"[a-z0-9][a-z0-9-]*\.(?:com|dev|io|me|net|org|app|tech|xyz|in|co\.uk|vercel\.app|github\.io)"
    r"(?:/\S*)?",
    re.IGNORECASE,
)

# Domains that are never somebody's portfolio.
_NOT_PORTFOLIO = ("linkedin.", "github.com", "twitter.", "x.com", "facebook.", "instagram.")

# A loose candidate run; validated afterwards rather than encoded in one regex.
_PHONE_CANDIDATE = re.compile(r"(?<![\w])[\d+()][\d+()\-.\s]{7,}[\d)]")

# The single most common phone false positive on a resume: an education or
# employment date range sitting in the header.
_YEAR_RANGE = re.compile(
    r"\b(19|20)\d{2}\s*[-–—]\s*((19|20)\d{2}|present|current)\b", re.IGNORECASE
)

# Words that mean a line is a job title, a document label, or a field caption —
# never a person's name. The line directly beneath the name is almost always
# the headline, and this list is what keeps it from winning.
_NAME_STOPWORDS = frozenset(
    {
        "resume",
        "cv",
        "curriculum",
        "vitae",
        "profile",
        "portfolio",
        "contact",
        "engineer",
        "developer",
        "manager",
        "analyst",
        "designer",
        "consultant",
        "architect",
        "scientist",
        "intern",
        "student",
        "graduate",
        "specialist",
        "administrator",
        "coordinator",
        "director",
        "officer",
        "lead",
        "senior",
        "junior",
        "phone",
        "mobile",
        "email",
        "address",
        "linkedin",
        "github",
        "objective",
        "summary",
        "about",
    }
)

# Segment separators used in the ubiquitous "City, Country | phone | email" line.
_SEGMENT_SPLIT = re.compile(r"[|•·–—\t]+")

_LOCATION = re.compile(
    r"^[A-Z][A-Za-z.'-]+(?:[ ][A-Z][A-Za-z.'-]+)*"
    r",\s*(?:[A-Z]{2}|[A-Z][A-Za-z.'-]+(?:[ ][A-Z][A-Za-z.'-]+)*)$"
)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _looks_like_phone(candidate: str, line: str, span: tuple[int, int]) -> bool:
    """Validate a candidate run of digits.

    Split from the pattern deliberately: a regex expressing all of this would be
    unreadable and impossible to adjust when a new false positive appears.
    """
    digits = _digits(candidate)

    # 15 is the E.164 maximum; below 7 it cannot be a dialable number.
    if not 7 <= len(digits) <= 15:
        return False

    # A date range on this line — the most common false positive by far.
    if _YEAR_RANGE.search(line):
        return False

    # Overlapping an email address. Checked by character span rather than by
    # "is there an @ on this line": headers overwhelmingly put the phone and
    # the email on the *same* line, so a line-level test rejects almost every
    # real phone number.
    start, end = span
    for email in _EMAIL.finditer(line):
        if start < email.end() and end > email.start():
            return False

    # A ZIP+4 or a bare digit run. Require some evidence of phone formatting:
    # a country code, brackets, or explicit grouping.
    return not (len(digits) < 10 and not any(ch in candidate for ch in "+()"))


def _find_phone(lines: list[str]) -> str | None:
    for line in lines:
        for match in _PHONE_CANDIDATE.finditer(line):
            raw = match.group(0)
            candidate = raw.strip(" .-")
            # Re-derive the span after stripping so the overlap test compares
            # the same text that will be returned.
            offset = match.start() + raw.index(candidate)
            if _looks_like_phone(candidate, line, (offset, offset + len(candidate))):
                # Original formatting, not digits: the user expects to see
                # "+91 98765 43210" exactly as they wrote it.
                return candidate
    return None


def _find_name(lines: list[str]) -> str | None:
    for line in lines[:5]:
        candidate = line.strip()
        if not candidate or len(candidate) > 60:
            continue

        lowered = candidate.lower()
        if any(word in lowered for word in _NAME_STOPWORDS):
            continue
        if "@" in candidate or "•" in candidate or "/" in candidate:
            continue
        if len(_digits(candidate)) >= 7:
            continue

        tokens = candidate.split()
        if not 2 <= len(tokens) <= 4:
            continue
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]{0,19}", token) for token in tokens):
            continue

        # Title-case only when the whole line is capitalised — a shouty header.
        # Anything already mixed-case is left exactly as written, so McDonald,
        # O'Brien and van der Berg survive intact.
        return candidate.title() if candidate.isupper() else candidate

    return None


def _find_location(lines: list[str]) -> str | None:
    for line in lines[:6]:
        for segment in _SEGMENT_SPLIT.split(line):
            candidate = segment.strip(" ,")
            if not candidate or len(candidate) > 60:
                continue
            if "@" in candidate or len(_digits(candidate)) >= 5:
                continue
            if any(word in candidate.lower() for word in _NAME_STOPWORDS):
                continue
            if _LOCATION.fullmatch(candidate):
                return candidate
    return None


def _mask(lines: list[str], values: list[str]) -> list[str]:
    """Blank out the parts of each line already claimed by a match."""
    masked = []
    for line in lines:
        for value in values:
            if value:
                line = line.replace(value, " ")
        masked.append(line)
    return masked


def head_of(text: str, limit: int = HEAD_LINES) -> str:
    """First few lines, for resumes with no detectable CONTACT section.

    `detect_sections` only emits CONTACT for text preceding the first heading,
    so a resume that opens with "SUMMARY" produces none at all.
    """
    return "\n".join(text.splitlines()[:limit])


def extract_contact(text: str) -> ContactDetails:
    """Pull contact details out of a resume header. Never raises."""
    if not text or not text.strip():
        return ContactDetails()

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ContactDetails()

    email_match = _EMAIL.search(text)
    email = email_match.group(0) if email_match else None

    linkedin_match = _LINKEDIN.search(text)
    linkedin = f"https://www.linkedin.com/in/{linkedin_match.group(1)}" if linkedin_match else None

    github = None
    github_match = _GITHUB.search(text)
    if github_match and github_match.group(1).lower() not in _GITHUB_RESERVED:
        github = f"https://github.com/{github_match.group(1)}"

    # Email addresses are removed before hunting for a portfolio URL: the
    # generic URL pattern happily matches the domain half of
    # "priya@example.com" and would publish the user's mail provider as their
    # personal site.
    without_emails = _EMAIL.sub(" ", text)

    portfolio = None
    for match in _GENERIC_URL.finditer(without_emails):
        url = match.group(0)
        if any(skip in url.lower() for skip in _NOT_PORTFOLIO):
            continue
        portfolio = url if url.startswith(("http://", "https://")) else f"https://{url}"
        break

    # Mask everything already identified before looking for free text, so a URL
    # or an email line cannot be mistaken for a name or a location.
    claimed = [v for v in (email, linkedin_match, github_match) if v]
    masked = _mask(
        lines,
        [email or "", *(m.group(0) for m in (linkedin_match, github_match) if m)]
        + ([portfolio.replace("https://", "")] if portfolio else []),
    )
    _ = claimed

    return ContactDetails(
        full_name=_find_name(masked),
        email=email,
        phone=_find_phone(lines),
        location=_find_location(masked),
        linkedin_url=linkedin,
        github_url=github,
        portfolio_url=portfolio,
    )
