"""Turn a raw job description into structured fields (US-3.1).

A pure function over text. No database, no I/O, nothing to await — which is why
this runs inside the request rather than on a background task.

**Deviation from api.md section 2.4, which specifies `202 Accepted`.** That shape
exists because resume parsing opens a PDF, and this does not: it is regex over a
few kilobytes of text, single-digit milliseconds, with no I/O at any point. The
interim task runner (ADR-018) is known to strand rows when the process restarts,
and paying that cost — plus a poll loop in the client — to defer five
milliseconds would be a worse system, not a more scalable one. The user pastes a
description and sees the parsed result in the same response.

When embeddings land in Phase 6 there will finally be something slow here, and
that is the change that moves this onto the real queue Phase 10 provides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    SalaryPeriod,
    WorkMode,
)
from app.services.job.normalization import (
    clean_description,
    content_hash,
    normalize_title,
)
from app.services.job.parsing import (
    find_company,
    find_employment_type,
    find_experience_level,
    find_experience_range,
    find_location,
    find_min_education,
    find_salary,
    find_title,
    find_work_mode,
)
from app.services.job.sections import (
    JobSectionType,
    detect_sections,
    extract_bullets,
    section_map,
)
from app.services.job.skills import JobSkillMention, extract_job_skills
from app.services.resume.skill_extraction import SkillMatcher

# A description shorter than this is not a job posting — it is a title someone
# pasted by mistake, or a truncated copy. Parsing it produces a row that scores
# against every candidate on almost no evidence.
MIN_DESCRIPTION_CHARS = 200


class UnparseableJobError(ValueError):
    """The text cannot be treated as a job description.

    Carries a message written for the person who pasted it, not for a log.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedJob:
    title: str
    company_name: str | None
    description_clean: str
    content_hash: str
    normalized_title: str
    responsibilities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    location: str | None = None
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    experience_level: ExperienceLevel | None = None
    min_years_experience: Decimal | None = None
    max_years_experience: Decimal | None = None
    min_education: EducationLevel | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    skills: list[JobSkillMention] = field(default_factory=list)


def parse_description(
    *,
    raw_text: str,
    matcher: SkillMatcher,
    title_hint: str | None = None,
    company_hint: str | None = None,
) -> ParsedJob:
    """Parse a description into the fields US-3.1 AC2 lists.

    `title_hint` and `company_hint` win over anything extracted. A user typing
    the title into the form, or an import supplying it as a column, knows better
    than a heuristic reading the first line — and a submitter who corrects the
    parser should not be overruled by it.

    Raises `UnparseableJobError` when the text is too short to be a posting. Every
    other field is optional: a description with no salary is normal, and
    inventing one would be worse than leaving it null (ADR-012).
    """
    cleaned = clean_description(raw_text)
    if len(cleaned) < MIN_DESCRIPTION_CHARS:
        raise UnparseableJobError(
            "That description is too short to parse. Paste the full posting, "
            f"including its requirements — at least {MIN_DESCRIPTION_CHARS} characters."
        )

    sections = detect_sections(cleaned)
    by_type = section_map(sections)

    title = (title_hint or "").strip() or find_title(cleaned)
    if not title:
        raise UnparseableJobError(
            "We couldn't find a job title. Add one, or make sure the posting's "
            "title is on its first line."
        )

    company = (company_hint or "").strip() or find_company(cleaned)
    experience = find_experience_range(cleaned)
    salary = find_salary(cleaned)

    return ParsedJob(
        title=title[:300],
        company_name=company[:200] if company else None,
        description_clean=cleaned,
        content_hash=content_hash(cleaned),
        normalized_title=normalize_title(title)[:300],
        responsibilities=extract_bullets(by_type.get(JobSectionType.RESPONSIBILITIES, "")),
        requirements=extract_bullets(by_type.get(JobSectionType.REQUIREMENTS, "")),
        benefits=extract_bullets(by_type.get(JobSectionType.BENEFITS, "")),
        location=find_location(cleaned),
        work_mode=find_work_mode(cleaned),
        employment_type=find_employment_type(cleaned),
        experience_level=find_experience_level(title, cleaned),
        min_years_experience=experience.min_years if experience else None,
        max_years_experience=experience.max_years if experience else None,
        min_education=find_min_education(cleaned),
        salary_min=salary.minimum if salary else None,
        salary_max=salary.maximum if salary else None,
        salary_currency=salary.currency if salary else None,
        salary_period=salary.period if salary else None,
        skills=extract_job_skills(matcher=matcher, sections=by_type, full_text=cleaned),
    )
