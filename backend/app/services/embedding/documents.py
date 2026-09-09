"""Turn a job or a candidate into the text that gets embedded.

**Not raw text** (ml.md section 3.2). A resume's formatting noise and boilerplate
— "References available upon request" — dilutes the signal, and a job advert
carries paragraphs of company marketing that say nothing about the role.

**Symmetric on both sides**, which is the part that matters. The two documents
use the same section names in the same order, so the model compares like with
like instead of comparing a formatted CV against a job board listing. Break the
symmetry and every similarity drops, in a way that looks like a model problem.

Pure functions, no I/O and no session: the caller loads the rows. That is what
makes these the easiest thing here to test, and they are the piece most likely
to need tuning once there are real numbers to look at in 6.4.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from app.models.career import EducationRecord, Project, WorkExperience
from app.models.enums import SkillRequirement
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import CandidateSkill

#: Bumped whenever the shape below changes.
#:
#: Part of the hash, so changing how a document is built invalidates every
#: stored hash and forces a re-embed. Without it, unchanged source text would
#: keep a vector that was built from a now-different document — a silent,
#: corpus-wide inconsistency with no symptom until the rankings look wrong.
DOCUMENT_VERSION = "v1"

#: Below this a document is not worth embedding. A job with only a title, or a
#: profile with nothing filled in, produces a vector that is mostly noise and
#: would sit in the corpus as a plausible-looking neighbour for anything.
MIN_CONTENT_CHARS = 80

#: Enough to carry the substance, short enough that one long resume cannot
#: dominate a batch. The model truncates at its own window anyway; this is about
#: what we choose to feed it.
_MAX_BULLETS = 12
_MAX_CHARS = 6000


def _years(minimum: Decimal | None, maximum: Decimal | None) -> str | None:
    if minimum is None and maximum is None:
        return None
    if minimum is not None and maximum is not None:
        return f"{minimum:g}-{maximum:g} years"
    if minimum is not None:
        return f"{minimum:g}+ years"
    return f"up to {maximum:g} years"


def _lines(label: str, values: list[str]) -> list[str]:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return []
    return [f"{label}: " + "; ".join(cleaned[:_MAX_BULLETS])]


def build_job_document(job: Job) -> str:
    """The text embedded for one job.

    Requirements and responsibilities come from the parser rather than
    `description_raw`, so company boilerplate never reaches the model. When the
    parse found neither, the raw description is the fallback — a job with no
    document at all would simply be missing from every comparison, which is
    worse than a noisy one.
    """
    required: list[str] = []
    preferred: list[str] = []
    for link in job.skills:
        name = link.skill.name
        if link.requirement is SkillRequirement.REQUIRED:
            required.append(name)
        else:
            preferred.append(name)

    parts: list[str] = [f"Title: {job.title.strip()}"]

    experience = _years(job.min_years_experience, job.max_years_experience)
    if experience is not None:
        parts.append(f"Experience: {experience}")

    parts.extend(_lines("Required", sorted(required)))
    parts.extend(_lines("Preferred", sorted(preferred)))
    parts.extend(_lines("Responsibilities", job.responsibilities))
    parts.extend(_lines("Requirements", job.requirements))

    if not job.responsibilities and not job.requirements:
        parts.append(f"Description: {job.description_raw.strip()}")

    return "\n".join(parts)[:_MAX_CHARS]


def build_candidate_document(
    *,
    profile: Profile | None,
    skills: list[CandidateSkill],
    experiences: list[WorkExperience],
    education: list[EducationRecord],
    projects: list[Project],
    total_years: Decimal | None,
) -> str:
    """The text embedded for one candidate.

    Built from the *live* profile and career rows rather than the resume's raw
    text — those rows are what the user has confirmed and corrected, and they
    are already normalised. It also means every version of one resume produces
    the same document, which is why only the current version is indexed.
    """
    parts: list[str] = []

    roles = profile.target_roles if profile is not None else []
    parts.extend(_lines("Roles", roles))

    if total_years is not None:
        parts.append(f"Experience: {total_years:g} years")

    parts.extend(_lines("Skills", sorted({link.skill.name for link in skills})))

    if profile is not None and profile.summary:
        parts.append(f"Summary: {profile.summary.strip()}")

    # Titles and highlights, not descriptions: a description is prose about a
    # company, a highlight is a claim about what the person did.
    role_lines: list[str] = []
    for row in experiences[:_MAX_BULLETS]:
        title = row.title.strip()
        if row.company_name:
            title = f"{title} at {row.company_name.strip()}"
        highlights = "; ".join(h.strip() for h in row.highlights[:3] if h.strip())
        role_lines.append(f"{title} — {highlights}" if highlights else title)
    parts.extend(_lines("Roles held", role_lines))

    parts.extend(
        _lines(
            "Education",
            [
                " ".join(
                    piece for piece in (row.degree, row.field_of_study, row.institution) if piece
                ).strip()
                for row in education[:_MAX_BULLETS]
            ],
        )
    )

    project_lines = [
        f"{row.name.strip()} — {row.description.strip()}" if row.description else row.name.strip()
        for row in projects[:_MAX_BULLETS]
    ]
    parts.extend(_lines("Projects", project_lines))

    return "\n".join(parts)[:_MAX_CHARS]


def document_hash(document: str) -> str:
    """What decides whether a document needs re-embedding.

    The version marker is inside the hash, so a change to how documents are
    built invalidates every stored one at once.
    """
    return hashlib.sha256(f"{DOCUMENT_VERSION}\n{document}".encode()).hexdigest()


def is_embeddable(document: str) -> bool:
    return len(document.strip()) >= MIN_CONTENT_CHARS
