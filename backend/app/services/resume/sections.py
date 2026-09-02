"""Resume section detection (ml.md section 2.2).

Rule-based, deliberately. Resume section headers are a small, near-closed
vocabulary — "EXPERIENCE", "Work History", "Technical Skills" and a few dozen
variants cover nearly everything. A classifier here would be slower, harder to
debug, and no more accurate on the actual distribution of headers; when it
missed a variant there would be no way to fix it except retraining.

A missed variant in this module is a one-line change to a tuple below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class SectionType(StrEnum):
    CONTACT = "CONTACT"
    SUMMARY = "SUMMARY"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    SKILLS = "SKILLS"
    PROJECTS = "PROJECTS"
    CERTIFICATIONS = "CERTIFICATIONS"
    ACHIEVEMENTS = "ACHIEVEMENTS"
    PUBLICATIONS = "PUBLICATIONS"
    LANGUAGES = "LANGUAGES"
    INTERESTS = "INTERESTS"
    REFERENCES = "REFERENCES"
    UNKNOWN = "UNKNOWN"


# Ordered longest-phrase-first within each group so "work experience" is not
# matched as "experience" with a stray "work" left over.
_HEADINGS: dict[SectionType, tuple[str, ...]] = {
    SectionType.SUMMARY: (
        "professional summary",
        "career summary",
        "executive summary",
        "career objective",
        "professional profile",
        "about me",
        "summary",
        "objective",
        "profile",
        "overview",
    ),
    SectionType.EXPERIENCE: (
        "professional experience",
        "work experience",
        "employment history",
        "career history",
        "relevant experience",
        "industry experience",
        "work history",
        "experience",
        "employment",
        "internships",
        "internship",
    ),
    SectionType.EDUCATION: (
        "education and training",
        "academic background",
        "academic qualifications",
        "educational qualifications",
        "education",
        "academics",
        "qualifications",
    ),
    SectionType.SKILLS: (
        "technical skills",
        "core competencies",
        "areas of expertise",
        "key skills",
        "skills and expertise",
        "technologies",
        "tech stack",
        "technical proficiencies",
        "competencies",
        "skills",
        "expertise",
    ),
    SectionType.PROJECTS: (
        "personal projects",
        "academic projects",
        "selected projects",
        "key projects",
        "projects",
        "portfolio",
    ),
    SectionType.CERTIFICATIONS: (
        "certifications and licenses",
        "licenses and certifications",
        "certifications",
        "certificates",
        "licenses",
        "credentials",
    ),
    SectionType.ACHIEVEMENTS: (
        "awards and honors",
        "honors and awards",
        "achievements",
        "accomplishments",
        "awards",
        "honors",
    ),
    SectionType.PUBLICATIONS: ("publications", "research", "papers"),
    SectionType.LANGUAGES: ("languages", "language proficiency"),
    SectionType.INTERESTS: ("interests", "hobbies", "activities"),
    SectionType.REFERENCES: ("references", "referees"),
    SectionType.CONTACT: ("contact", "contact information", "personal details"),
}

# Longest first overall, so a line reading "technical skills" cannot be claimed
# by the shorter "skills" entry first.
_LOOKUP: list[tuple[str, SectionType]] = sorted(
    ((phrase, section) for section, phrases in _HEADINGS.items() for phrase in phrases),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

# Decorative characters resumes wrap headings in: "--- EXPERIENCE ---",
# ">> SKILLS <<", "◆ EDUCATION".
_DECORATION = re.compile(r"^[\s\-=_*~#>◆■□●•\[\]|:]+|[\s\-=_*~#<◆■□●•\[\]|:]+$")

# A heading is short. This is the single most effective signal: a 200-character
# line mentioning "experience" is prose, not a header.
MAX_HEADING_LENGTH = 60


@dataclass(frozen=True, slots=True)
class Section:
    type: SectionType
    heading: str
    text: str
    start: int
    end: int

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _clean(line: str) -> str:
    return _DECORATION.sub("", line).strip()


def classify_heading(line: str) -> SectionType | None:
    """Return the section a line introduces, or None if it is not a heading.

    Requires an exact match on the cleaned line rather than a substring search.
    "Skills" is a heading; "I used these skills daily" contains the word and is
    plainly not one.
    """
    cleaned = _clean(line)
    if not cleaned or len(cleaned) > MAX_HEADING_LENGTH:
        return None

    # Trailing colon is common and carries no meaning: "SKILLS:".
    normalized = cleaned.rstrip(":").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)

    if not normalized:
        return None

    for phrase, section in _LOOKUP:
        if normalized == phrase:
            return section

    # A short ALL-CAPS line that ends with a known word is still a heading:
    # "TECHNICAL SKILLS & TOOLS". Restricted to upper case because that formatting
    # is itself the evidence — the same words in sentence case are usually prose.
    if cleaned.isupper() and len(normalized.split()) <= 5:
        for phrase, section in _LOOKUP:
            if normalized.startswith(phrase + " ") or normalized.endswith(" " + phrase):
                return section

    return None


def detect_sections(text: str) -> list[Section]:
    """Split a resume into sections.

    Content before the first recognised heading becomes a CONTACT section: on
    almost every resume that region holds the name and contact details.
    """
    lines = text.splitlines()
    if not lines:
        return []

    # (line index, section type, heading text)
    boundaries: list[tuple[int, SectionType, str]] = []
    for index, line in enumerate(lines):
        section = classify_heading(line)
        if section is not None:
            boundaries.append((index, section, _clean(line)))

    # Character offset of each line, so spans point back into the original text
    # (US-2.3 AC2 requires extracted entities to cite their source span).
    offsets: list[int] = []
    running = 0
    for line in lines:
        offsets.append(running)
        running += len(line) + 1

    def slice_text(start_line: int, end_line: int) -> tuple[str, int, int]:
        body = "\n".join(lines[start_line:end_line]).strip()
        start = offsets[start_line] if start_line < len(offsets) else len(text)
        end = offsets[end_line] if end_line < len(offsets) else len(text)
        return body, start, end

    sections: list[Section] = []

    if not boundaries:
        body, start, end = slice_text(0, len(lines))
        return [Section(SectionType.UNKNOWN, "", body, start, end)]

    first_heading_line = boundaries[0][0]
    if first_heading_line > 0:
        body, start, end = slice_text(0, first_heading_line)
        if body:
            sections.append(Section(SectionType.CONTACT, "", body, start, end))

    for position, (line_index, section_type, heading) in enumerate(boundaries):
        next_line = boundaries[position + 1][0] if position + 1 < len(boundaries) else len(lines)
        # Skip the heading line itself; the section is what follows it.
        body, start, end = slice_text(line_index + 1, next_line)
        sections.append(Section(section_type, heading, body, start, end))

    return sections


def section_map(sections: list[Section]) -> dict[SectionType, str]:
    """Combined text per section type.

    Resumes legitimately repeat a section — "Technical Skills" and "Other
    Skills" — so bodies are concatenated rather than the last one winning.
    """
    merged: dict[SectionType, list[str]] = {}
    for section in sections:
        if section.text.strip():
            merged.setdefault(section.type, []).append(section.text)
    return {key: "\n".join(values) for key, values in merged.items()}
