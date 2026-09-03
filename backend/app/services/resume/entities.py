"""Structured entity extraction from resume sections (US-2.3 AC1).

Turns the EXPERIENCE, EDUCATION, PROJECTS and CERTIFICATIONS blocks into rows.
Pure functions, no database, same shape as `contact.py` and for the same
reason — this is the part most worth testing in isolation.

**The governing rule is the one ADR-012 sets: never invent.** A wrong employer or
a wrong start date is worse than a missing one, because it silently changes the
years-of-experience figure the ranking formula reads and the user has no way to
see that it was guessed. Every heuristic here fails closed.

Entries are found by their dates. Almost every resume, whatever its layout,
puts a date range on or beside the line that starts a new entry, and nothing
else in a bullet list looks like one. That anchor is far more reliable than
trying to recognise formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.models.enums import EducationLevel, EmploymentType
from app.services.resume.dates import (
    MONTH_NAME_PATTERN,
    DateRange,
    find_date_range,
    format_month,
)
from app.services.resume.sections import SectionType

# Confidence by how much structure the entry actually had. An entry whose title
# and employer were separated by an explicit delimiter is a stronger reading
# than one where they had to be split apart by vocabulary.
_CONFIDENCE_EXPLICIT = 0.90
_CONFIDENCE_INFERRED = 0.70
# Below this nothing is written. Same threshold as skill extraction.
MIN_CONFIDENCE = 0.60

_BULLET = re.compile(r"^[\s]*[•●▪◦‣*\-\u2013\u2014]\s+|^[\s]*\d+[.)]\s+")
# What separates a title from an employer on one line. Comma last: it also
# appears inside "Bengaluru, India".
_DELIMITERS = re.compile(r"\s*(?:\||•|·|\u2014|\u2013|@|\bat\b|\bwith\b)\s*", re.IGNORECASE)

# Words that mark a segment as the role rather than the employer. This is what
# decides which half of "Acme Technologies | Software Engineer" is which.
_ROLE_WORDS = re.compile(
    r"\b(engineer|developer|programmer|architect|analyst|scientist|manager|lead|director|"
    r"consultant|designer|administrator|specialist|intern|trainee|associate|executive|officer|"
    r"head|president|founder|freelancer|freelance|contractor|researcher|instructor|teacher|"
    r"assistant|coordinator|strategist|marketer|recruiter|accountant|auditor|"
    r"sde|swe|qa|devops|sre|pm|tpm)\b",
    re.IGNORECASE,
)

# Words that mark a segment as the employer.
_COMPANY_WORDS = re.compile(
    r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|llp|plc|gmbh|pvt|private|"
    r"technologies|technology|tech|solutions|systems|labs|laboratories|software|services|"
    r"consulting|group|holdings|industries|enterprises|studio|agency|partners|ventures|"
    r"university|college|institute|school|hospital|bank|foundation)\b",
    re.IGNORECASE,
)

_EMPLOYMENT_HINTS: tuple[tuple[EmploymentType, re.Pattern[str]], ...] = (
    (EmploymentType.INTERNSHIP, re.compile(r"\b(intern|internship|trainee)\b", re.I)),
    (EmploymentType.CONTRACT, re.compile(r"\b(contract|contractor|freelance|consultant)\b", re.I)),
    (EmploymentType.PART_TIME, re.compile(r"\bpart[\s-]?time\b", re.I)),
    (EmploymentType.FULL_TIME, re.compile(r"\bfull[\s-]?time\b", re.I)),
)

_DEGREE_LEVELS: tuple[tuple[EducationLevel, re.Pattern[str]], ...] = (
    (EducationLevel.DOCTORATE, re.compile(r"\b(ph\.?\s?d|doctorate|doctoral)\b", re.I)),
    (
        EducationLevel.MASTERS,
        re.compile(
            r"\b(master'?s?|m\.?\s?tech|m\.?\s?e\b|m\.?\s?sc|m\.?\s?c\.?a|m\.?\s?b\.?a|"
            r"m\.?\s?s\b|m\.?\s?com|post\s*graduate|pgdm)\b",
            re.I,
        ),
    ),
    (
        EducationLevel.BACHELORS,
        re.compile(
            r"\b(bachelor'?s?|b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|b\.?\s?c\.?a|b\.?\s?a\b|"
            r"b\.?\s?com|b\.?\s?s\b|undergraduate)\b",
            re.I,
        ),
    ),
    (EducationLevel.DIPLOMA, re.compile(r"\b(diploma|polytechnic)\b", re.I)),
    (
        EducationLevel.HIGH_SCHOOL,
        re.compile(r"\b(high\s+school|higher\s+secondary|senior\s+secondary|12th|hsc|xii)\b", re.I),
    ),
)

_INSTITUTION_WORDS = re.compile(
    r"\b(university|college|institute|institution|school|academy|iit|nit|iiit|bits|polytechnic)\b",
    re.IGNORECASE,
)

# "CGPA: 9.1", "8.4 CGPA", "GPA 3.8/4.0", "72.5%", "First Class".
#
# Ordered, and tried in order rather than as one alternation. A single pattern
# scans left to right by *position*, so in "2016 - 2020 CGPA: 8.4" the
# number-then-label form matches "2020 CGPA" before the label-then-number form
# ever reaches the real grade. Label-first is the least ambiguous, so it goes
# first and wins outright.
_GRADE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:cgpa|gpa|sgpa|percentage|marks)\s*[:\-]?\s*([\d.]+\s*(?:/\s*[\d.]+)?)",
        re.IGNORECASE,
    ),
    re.compile(r"\b([\d.]+)\s*(?:cgpa|gpa)\b", re.IGNORECASE),
    re.compile(r"\b([\d.]+\s*%)", re.IGNORECASE),
    re.compile(
        r"\b(first\s+class(?:\s+with\s+distinction)?|distinction|second\s+class)\b",
        re.IGNORECASE,
    ),
)


def _find_grade(text: str) -> str | None:
    """A grade as written, or nothing.

    Numeric candidates that look like a year are rejected: "2016 - 2020" sits
    next to the grade on almost every education entry, and reporting a
    graduation year as a CGPA would be visibly wrong on the profile.
    """
    for pattern in _GRADE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        value = match.group(1).strip()
        leading = re.match(r"[\d.]+", value)
        if leading is not None:
            try:
                number = float(leading.group(0).rstrip("."))
            except ValueError:
                continue
            # A grade is a small number or a percentage; 1900-2100 is a year.
            if number > 100 or 1900 <= number <= 2100:
                continue
        return value
    return None


_URL = re.compile(r"https?://[^\s,)\]]+|(?<![\w@.])(?:www\.|github\.com/)[^\s,)\]]+", re.IGNORECASE)

_CERT_ISSUERS = re.compile(
    r"\b(aws|amazon\s+web\s+services|microsoft|azure|google|gcp|oracle|cisco|comptia|"
    r"red\s?hat|vmware|salesforce|ibm|coursera|udemy|udacity|linkedin|hackerrank|"
    r"scrum\s?alliance|pmi|databricks|snowflake|kubernetes|linux\s+foundation)\b",
    re.IGNORECASE,
)

_MAX_ENTRIES = 25


@dataclass(frozen=True, slots=True)
class ExperienceEntry:
    title: str
    company_name: str | None
    location: str | None
    employment_type: EmploymentType | None
    dates: DateRange
    highlights: list[str]
    confidence: float

    @property
    def content_key(self) -> str:
        return experience_key(self.title, self.company_name, self.dates.start)


@dataclass(frozen=True, slots=True)
class EducationEntry:
    institution: str
    degree: str | None
    field_of_study: str | None
    level: EducationLevel | None
    grade: str | None
    dates: DateRange
    confidence: float

    @property
    def content_key(self) -> str:
        return education_key(self.institution, self.degree, self.dates.end)


@dataclass(frozen=True, slots=True)
class ProjectEntry:
    name: str
    description: str | None
    url: str | None
    highlights: list[str]
    dates: DateRange
    confidence: float

    @property
    def content_key(self) -> str:
        return project_key(self.name)


@dataclass(frozen=True, slots=True)
class CertificationEntry:
    name: str
    issuer: str | None
    dates: DateRange
    confidence: float

    @property
    def content_key(self) -> str:
        return certification_key(self.name, self.issuer)


@dataclass(frozen=True, slots=True)
class ExtractedEntities:
    experiences: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    certifications: list[CertificationEntry] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.experiences)
            + len(self.education)
            + len(self.projects)
            + len(self.certifications)
        )


def _key(prefix: str, *parts: str | None) -> str:
    """Stable fingerprint for idempotent re-parsing.

    Normalised hard — lowercased, punctuation stripped — so a re-parse whose
    extractor reads spacing or capitalisation differently still matches the
    existing row instead of inserting a second copy of the same job.
    """
    cleaned = [re.sub(r"[^a-z0-9]+", "", (p or "").lower()) for p in parts]
    return f"{prefix}:{':'.join(cleaned)}"[:200]


# Public key builders. A row the user types in by hand gets its key the same
# way an extracted one does, so a later parse of the same entity updates it
# rather than inserting a duplicate — and the is_user_verified guard then
# stops that update from overwriting their wording.
#
# A key is assigned once and never recomputed. It identifies the entity *to
# the parser*, not to the reader: editing "Acme" to "Acme Inc" must not change
# it, or the next parse would find no match and insert a second row.


def experience_key(title: str, company: str | None, start: date | None) -> str:
    return _key("exp", title, company, format_month(start))


def education_key(institution: str, degree: str | None, end: date | None) -> str:
    return _key("edu", institution, degree, format_month(end))


def project_key(name: str) -> str:
    return _key("proj", name, None, None)


def certification_key(name: str, issuer: str | None) -> str:
    return _key("cert", name, issuer)


def _is_bullet(line: str) -> bool:
    return _BULLET.match(line) is not None


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line).strip()


@dataclass(frozen=True, slots=True)
class _Block:
    """One entry: the lines around a date anchor, plus its bullets."""

    header_lines: list[str]
    bullets: list[str]
    dates: DateRange
    # Plain lines that came *after* this block's date anchor. They may equally
    # be the header of the next entry — nothing can tell until a date appears —
    # so they are recorded in both places and each reader takes what it
    # recognises. Education finds "CGPA: 8.4" here; experience ignores them.
    detail_lines: list[str]


def _split_into_blocks(text: str) -> list[_Block]:
    """Cut a section into entries, using date lines as the anchor.

    Header lines are the non-bullet lines since the previous entry ended. That
    covers both common layouts — dates on their own line under the title, and
    dates right-aligned onto the title line itself — without needing to know
    which one is in play.
    """
    lines = [line for line in text.splitlines() if line.strip()]

    blocks: list[_Block] = []
    pending_header: list[str] = []
    current: _Block | None = None

    for line in lines:
        stripped = line.strip()

        if _is_bullet(line):
            if current is not None:
                current.bullets.append(_strip_bullet(line))
            # A bullet before any dated line belongs to no entry. Dropped
            # rather than attached to the next one, which it precedes.
            continue

        dates = find_date_range(stripped)
        if not dates.is_empty:
            # This line anchors a new entry. Anything unclaimed above it is its
            # header.
            current = _Block(
                header_lines=[*pending_header, stripped],
                bullets=[],
                dates=dates,
                detail_lines=[],
            )
            blocks.append(current)
            pending_header = []
            continue

        # A plain line. It either heads the next entry or continues this one's
        # header, and we cannot tell which until a date appears.
        if current is not None:
            current.detail_lines.append(stripped)
        pending_header.append(stripped)
        # Two unclaimed lines is a header; more than that is prose, and keeping
        # it would drag a paragraph into the next entry's title.
        if len(pending_header) > 3:
            pending_header = pending_header[-3:]

    return blocks[:_MAX_ENTRIES]


# Dates and open-ended markers, removed from a header fragment before it is
# read as a title or an employer.
#
# The month alternation is closed and `\b`-anchored on both sides. An earlier
# version matched a prefix plus `[a-z]*`, which silently turned "Junior
# Developer" into "Developer" — "Jun" is a month, and nothing downstream could
# tell that a word had been eaten.
_DATE_NOISE = re.compile(
    rf"\b(?:19|20)\d{{2}}\b|\b(?:{MONTH_NAME_PATTERN})\.?\b"
    r"|\bpresent\b|\bcurrent(?:ly)?\b|\btill\s*date\b|\bto\s*date\b|\bongoing\b",
    re.IGNORECASE,
)


def _clean_segment(segment: str) -> str:
    """Drop dates and trailing punctuation from a header fragment."""
    cleaned = re.sub(r"\s+", " ", _DATE_NOISE.sub(" ", segment))
    return cleaned.strip(" ,;:|-\u2013\u2014•·()[]")


def _looks_like_location(segment: str) -> bool:
    """ "Bengaluru, India" — two or three capitalised words, no role or company word."""
    if _ROLE_WORDS.search(segment) or _COMPANY_WORDS.search(segment):
        return False
    words = segment.split()
    return 1 <= len(words) <= 4 and "," in segment


def _split_header(header_lines: list[str]) -> tuple[list[str], bool]:
    """Header fragments, and whether an explicit delimiter separated them.

    The flag decides confidence: an author who wrote "Software Engineer | Acme"
    told us where the boundary is. Splitting "Software Engineer Acme" by
    vocabulary is a guess, and is scored as one.
    """
    segments: list[str] = []
    explicit = False

    for line in header_lines:
        parts = [p for p in _DELIMITERS.split(line) if p.strip()]
        if len(parts) > 1:
            explicit = True

        for part in parts:
            cleaned = _clean_segment(part)
            if not cleaned:
                continue
            comma_split = _split_on_comma(cleaned)
            if comma_split is not None:
                explicit = True
                segments.extend(comma_split)
            else:
                segments.append(cleaned)

    return [s for s in segments if s], explicit


def _split_on_comma(segment: str) -> list[str] | None:
    """Split "Backend Engineer, Zenith Systems" — but not "Bengaluru, India".

    The comma is not in `_DELIMITERS` because it is at least as common inside a
    place name as between a role and an employer. It is safe to split on only
    when it separates something that reads as a role from something that does
    not, which is exactly the ambiguity a blanket rule gets wrong.
    """
    if "," not in segment:
        return None

    left, _, right = segment.partition(",")
    left, right = left.strip(), right.strip()
    if not left or not right:
        return None

    left_is_role = _ROLE_WORDS.search(left) is not None
    right_is_role = _ROLE_WORDS.search(right) is not None
    # Exactly one side is a role. Both or neither means the comma is doing
    # something else — "Bengaluru, India", or a two-part title.
    if left_is_role == right_is_role:
        return None

    return [left, right]


def extract_experiences(text: str) -> list[ExperienceEntry]:
    entries: list[ExperienceEntry] = []

    for block in _split_into_blocks(text):
        segments, explicit = _split_header(block.header_lines)
        if not segments:
            continue

        location = next((s for s in segments if _looks_like_location(s)), None)
        rest = [s for s in segments if s != location]

        title = next((s for s in rest if _ROLE_WORDS.search(s)), None)
        if title is None:
            # No recognisable role. Skipping loses the entry, but naming
            # someone's job title wrongly is worse — it is quoted back to them
            # and scored against every job.
            continue

        company = next((s for s in rest if s != title and _COMPANY_WORDS.search(s)), None)
        if company is None:
            # Fall back to the other segment, whatever it is. With a delimiter
            # the author said these are two different things, so the one that
            # is not the role is the employer.
            company = next((s for s in rest if s != title), None)

        joined = " ".join(block.header_lines)
        employment_type = next(
            (t for t, pattern in _EMPLOYMENT_HINTS if pattern.search(joined)), None
        )

        confidence = _CONFIDENCE_EXPLICIT if explicit else _CONFIDENCE_INFERRED
        if confidence < MIN_CONFIDENCE:
            continue

        entries.append(
            ExperienceEntry(
                title=title[:200],
                company_name=company[:200] if company else None,
                location=location[:200] if location else None,
                employment_type=employment_type,
                dates=block.dates,
                highlights=[h[:500] for h in block.bullets[:15]],
                confidence=confidence,
            )
        )

    return _deduplicate(entries)


def extract_education(text: str) -> list[EducationEntry]:
    entries: list[EducationEntry] = []

    for block in _split_into_blocks(text):
        segments, explicit = _split_header(block.header_lines)
        if not segments:
            continue

        # detail_lines included: "CGPA: 8.4" and "First Class" are written on
        # the line *after* the dates as often as before them.
        joined = " ".join([*block.header_lines, *block.detail_lines, *block.bullets])

        institution = next((s for s in segments if _INSTITUTION_WORDS.search(s)), None)
        level = next((lv for lv, pattern in _DEGREE_LEVELS if pattern.search(joined)), None)
        degree = next(
            (s for s in segments if any(p.search(s) for _, p in _DEGREE_LEVELS)),
            None,
        )

        if institution is None:
            # Without a named institution there is nothing to attribute the
            # degree to, and a bare "B.Tech" row helps nobody.
            continue

        field_of_study = None
        if degree is not None:
            # "B.Tech in Computer Science" — the part after "in".
            match = re.search(r"\bin\s+(.+)$", degree, re.IGNORECASE)
            if match is not None:
                field_of_study = match.group(1).strip(" .,")

        grade = _find_grade(joined)

        entries.append(
            EducationEntry(
                institution=institution[:200],
                degree=degree[:200] if degree else None,
                field_of_study=field_of_study[:200] if field_of_study else None,
                level=level,
                grade=grade.strip()[:50] if grade else None,
                dates=block.dates,
                confidence=_CONFIDENCE_EXPLICIT
                if explicit or level is not None
                else _CONFIDENCE_INFERRED,
            )
        )

    return _deduplicate(entries)


def extract_projects(text: str) -> list[ProjectEntry]:
    """Projects, which unlike experience often carry no dates at all.

    So the anchor is different: a short line starts a project, and everything
    under it until the next short line belongs to it. That is looser than the
    date anchor and would be far too loose for experience — but a projects
    section is almost always exactly this shape.
    """
    lines = [line for line in text.splitlines() if line.strip()]

    entries: list[ProjectEntry] = []
    name: str | None = None
    bullets: list[str] = []
    prose: list[str] = []
    dates = DateRange(None, None, False)
    url: str | None = None

    def flush() -> None:
        nonlocal name, bullets, prose, dates, url
        body = bullets or prose
        if name is not None and (body or url is not None or not dates.is_empty):
            entries.append(
                ProjectEntry(
                    name=name[:200],
                    description=(
                        " ".join(prose)[:1000] if prose else (body[0][:1000] if body else None)
                    ),
                    url=url,
                    highlights=[h[:500] for h in bullets[:10]],
                    dates=dates,
                    confidence=_CONFIDENCE_EXPLICIT,
                )
            )
        name, bullets, prose, dates, url = None, [], [], DateRange(None, None, False), None

    def is_prose(value: str) -> bool:
        """A description sentence rather than the next project's name.

        Projects are as often written as a name plus a paragraph as a name plus
        bullets. Without this, every sentence of the paragraph starts a new
        project and the real one is dropped for having no body.
        """
        return len(value) > 60 or value.endswith(".") or len(value.split()) > 9

    for line in lines:
        stripped = line.strip()

        if _is_bullet(line):
            content = _strip_bullet(line)
            bullets.append(content)
            if url is None:
                found = _URL.search(content)
                url = found.group(0) if found else None
            continue

        if name is not None and is_prose(stripped):
            prose.append(stripped)
            if url is None:
                found = _URL.search(stripped)
                url = found.group(0) if found else None
            continue

        flush()
        dates = find_date_range(stripped)
        found = _URL.search(stripped)
        url = found.group(0) if found else None
        # The name is the line with dates and links taken out of it.
        candidate = _clean_segment(_URL.sub(" ", stripped))
        candidate = _DELIMITERS.split(candidate)[0].strip()
        name = candidate if candidate else None

    flush()
    return _deduplicate(entries[:_MAX_ENTRIES])


def extract_certifications(text: str) -> list[CertificationEntry]:
    """One per line — certifications are a list, not a set of blocks."""
    entries: list[CertificationEntry] = []

    for line in text.splitlines():
        stripped = _strip_bullet(line) if _is_bullet(line) else line.strip()
        if not stripped or len(stripped) > 200:
            continue

        # A certification line carries an issue date, sometimes an expiry —
        # not a range. Dashes in these lines belong to the name ("AWS Certified
        # Solutions Architect - Associate"), so a lone date found on the right
        # of one is the issue date, not an end date.
        found = find_date_range(stripped)
        dates = (
            DateRange(found.end, None, False)
            if found.start is None and found.end is not None
            else found
        )
        name = _clean_segment(_URL.sub(" ", stripped))
        # Two words minimum: a stray year or a section fragment is not a
        # certification name.
        if len(name.split()) < 2:
            continue

        issuer_match = _CERT_ISSUERS.search(stripped)
        issuer = issuer_match.group(0) if issuer_match else None

        # Drop a segment that is *only* the issuer — "Azure Fundamentals |
        # Microsoft". An issuer embedded in the name is left alone: "AWS
        # Certified Solutions Architect - Associate" is the certification's
        # actual name, and stripping the half containing "AWS" would leave
        # "Associate".
        if issuer is not None:
            parts = [p.strip() for p in _DELIMITERS.split(name) if p.strip()]
            kept = [p for p in parts if p.lower() != issuer.lower()]
            if kept and len(kept) < len(parts):
                name = " \u2013 ".join(kept)

        entries.append(
            CertificationEntry(
                name=name[:200],
                issuer=issuer[:200] if issuer else None,
                dates=dates,
                confidence=_CONFIDENCE_EXPLICIT if issuer is not None else _CONFIDENCE_INFERRED,
            )
        )

    return _deduplicate(entries[:_MAX_ENTRIES])


def _deduplicate[T](entries: list[T]) -> list[T]:
    """Keep the first of any two entries sharing a content key.

    Resumes repeat things — a role listed once in a summary and again in the
    history — and two rows with the same key would violate the unique index on
    the way in.
    """
    seen: set[str] = set()
    unique: list[T] = []
    for entry in entries:
        key = entry.content_key  # type: ignore[attr-defined]
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def extract_entities(sections: dict[SectionType, str]) -> ExtractedEntities:
    """Everything US-2.3 AC1 asks for beyond contact details and skills.

    Driven off detected sections rather than the whole document: a date range
    in a summary paragraph is not a job, and scanning everywhere would turn
    every "2019" into an entry.
    """
    return ExtractedEntities(
        experiences=extract_experiences(sections.get(SectionType.EXPERIENCE, "")),
        education=extract_education(sections.get(SectionType.EDUCATION, "")),
        projects=extract_projects(sections.get(SectionType.PROJECTS, "")),
        certifications=extract_certifications(sections.get(SectionType.CERTIFICATIONS, "")),
    )
