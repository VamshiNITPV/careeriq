"""Skill extraction from a job description.

Reuses `SkillMatcher` from the resume side — the same taxonomy, the same alias
resolution, the same longest-match-wins scan. Sharing it is the point: a
candidate's "Postgres" and a job's "PostgreSQL" must resolve to one id before
any scoring can compare them, and two separate matchers would eventually drift.

What is *not* shared is the interpretation. A resume section says how strongly
someone claims a skill; a job section says how badly the employer needs it, and
that maps to REQUIRED versus PREFERRED — the distinction the skill dimension of
the ranking formula weights (ml.md section 4.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import SkillRequirement
from app.services.job.sections import JobSectionType
from app.services.resume.skill_extraction import SkillMatcher

# Where a mention was found decides both how much to trust it and whether the
# employer treats it as mandatory.
#
# ABOUT is the company blurb: "we are a Python shop" is real evidence the role
# involves Python, but far weaker than a requirements bullet, and it is never
# mandatory on its own.
_SECTION_RULES: dict[JobSectionType, tuple[SkillRequirement, float]] = {
    JobSectionType.REQUIREMENTS: (SkillRequirement.REQUIRED, 0.95),
    JobSectionType.RESPONSIBILITIES: (SkillRequirement.REQUIRED, 0.80),
    JobSectionType.NICE_TO_HAVE: (SkillRequirement.PREFERRED, 0.90),
    JobSectionType.BENEFITS: (SkillRequirement.PREFERRED, 0.40),
    JobSectionType.ABOUT: (SkillRequirement.PREFERRED, 0.55),
    JobSectionType.UNKNOWN: (SkillRequirement.REQUIRED, 0.60),
}

# Below this a mention is not written to job_skills. A wrongly-required skill
# penalises every candidate who lacks it, on every ranking, invisibly.
MIN_CONFIDENCE = 0.55

_REPEAT_BONUS = 0.03
_MAX_CONFIDENCE = 0.99

# Inline hedging that demotes a REQUIRED match found in a requirements block.
# Postings routinely put "familiarity with Kubernetes is a plus" inside the
# requirements list, and reading that as mandatory is the single most common way
# to over-constrain a match.
_PREFERRED_HINT = re.compile(
    r"\b(nice\s+to\s+have|a\s+plus|is\s+a\s+bonus|bonus|preferred|desirable|"
    r"would\s+be\s+(?:a\s+)?(?:plus|great|nice)|good\s+to\s+have|optional|"
    r"familiarity\s+with|exposure\s+to|awareness\s+of)\b",
    re.IGNORECASE,
)

# "3+ years of Python", "2 years experience in Java" — a per-skill minimum,
# distinct from the role's overall experience range.
_SKILL_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-|\u2013|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE
)
_MAX_PLAUSIBLE_YEARS = 30


@dataclass(frozen=True, slots=True)
class JobSkillMention:
    canonical_name: str
    requirement: SkillRequirement
    confidence: float
    min_years: Decimal | None
    section: JobSectionType
    evidence: str


def _line_around(text: str, start: int, end: int) -> str:
    """The line a match sits on, for hedge detection and evidence."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _years_near(line: str) -> Decimal | None:
    """A per-skill experience minimum stated on the same line."""
    match = _SKILL_YEARS.search(line)
    if match is None:
        return None
    years = int(match.group(1))
    return Decimal(years) if 0 < years <= _MAX_PLAUSIBLE_YEARS else None


def extract_job_skills(
    *,
    matcher: SkillMatcher,
    sections: dict[JobSectionType, str],
    full_text: str,
) -> list[JobSkillMention]:
    """Find the skills a posting asks for, and how badly.

    Falls back to scanning the whole description when no sections were detected,
    at the lower confidence an unstructured match deserves — many real postings
    are a single unbroken paragraph.
    """
    blocks = sections or {JobSectionType.UNKNOWN: full_text}

    found: dict[str, list[JobSkillMention]] = {}

    for section_type, text in blocks.items():
        requirement, base_confidence = _SECTION_RULES.get(
            section_type, (SkillRequirement.REQUIRED, 0.60)
        )

        for span in matcher.find_spans(text):
            line = _line_around(text, span.start, span.end)

            # A hedge on the line overrides the section's verdict. The section
            # says where the employer filed it; the sentence says what they
            # actually meant.
            if requirement is SkillRequirement.REQUIRED and _PREFERRED_HINT.search(line):
                mention_requirement = SkillRequirement.PREFERRED
                confidence = base_confidence
            else:
                mention_requirement = requirement
                confidence = base_confidence

            found.setdefault(span.canonical_name, []).append(
                JobSkillMention(
                    canonical_name=span.canonical_name,
                    requirement=mention_requirement,
                    confidence=confidence,
                    min_years=_years_near(line),
                    section=section_type,
                    evidence=line[:300],
                )
            )

    merged: list[JobSkillMention] = []
    for canonical, mentions in found.items():
        # REQUIRED wins over PREFERRED when a skill appears in both. A posting
        # that lists Python under requirements and again under nice-to-haves
        # requires Python; treating it as optional would under-penalise a
        # candidate who lacks it.
        required = [m for m in mentions if m.requirement is SkillRequirement.REQUIRED]
        pool = required or mentions
        best = max(pool, key=lambda m: m.confidence)

        confidence = min(_MAX_CONFIDENCE, best.confidence + _REPEAT_BONUS * (len(mentions) - 1))
        years = next((m.min_years for m in pool if m.min_years is not None), None)

        if confidence < MIN_CONFIDENCE:
            continue

        merged.append(
            JobSkillMention(
                canonical_name=canonical,
                requirement=best.requirement,
                confidence=round(confidence, 3),
                min_years=years,
                section=best.section,
                evidence=best.evidence,
            )
        )

    return sorted(
        merged,
        key=lambda m: (
            m.requirement is not SkillRequirement.REQUIRED,
            -m.confidence,
            m.canonical_name,
        ),
    )
