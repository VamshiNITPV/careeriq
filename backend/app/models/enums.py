"""Enumerated types shared by models and schemas.

These map to native PostgreSQL ENUM types (database.md section 2). Native enums
give database-level validation; the cost is that adding a value needs a
migration, which is the right amount of friction for a closed vocabulary.

Each member's value equals its name. That is deliberate: SQLAlchemy persists the
member *name* by default while Pydantic serialises the *value*, and letting the
two differ produces a mismatch that only shows up at the API boundary.

Only the enums Phase 2 needs are defined. The rest arrive with the tables that
use them, rather than sitting here unused for months.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Coarse authorization role (ADR-014).

    Per-resource ownership is checked separately; this is only the role gate.
    """

    USER = "USER"
    ADMIN = "ADMIN"


class AuthProvider(StrEnum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"


class VerificationPurpose(StrEnum):
    """What a one-time token is for.

    One table with a purpose column rather than two near-identical tables. The
    rows have the same shape and the same lifecycle; the only differences are
    lifetime and what consuming one does, both of which are behaviour, not
    storage. Splitting them would duplicate the issue/consume/expire logic.
    """

    # noqa: the linter flags any assignment to a name containing "password" as
    # a hardcoded credential. These are enum labels, not secrets.
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"


class ProcessingStatus(StrEnum):
    """Stages of the resume pipeline (ADR-009).

    Ordered as the pipeline runs. FAILED is terminal and always carries a
    reason — a task that simply stops with no explanation is unusable to both
    the user and whoever debugs it (US-2.2 AC2).
    """

    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    PARSING = "PARSING"
    EMBEDDING = "EMBEDDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class RecommendationFeedback(StrEnum):
    """What a user said about a recommendation (api.md section 2.5).

    Nothing reads these yet, and that is the point: a learned ranker needs
    labelled relevance judgements, and those can only be collected forward in
    time (ADR-005). Starting to collect them in Phase 6.3 is what stops Phase
    6.4's evaluation set being built entirely by hand.

    NOT_RELEVANT and NOT_INTERESTED are separate because they mean opposite
    things to a ranker. "This is not a match for me" is a statement about the
    scoring being wrong; "I am not interested" can sit on a perfectly scored
    job the user simply does not want. Collapsing them would teach a future
    model that a correct prediction was an error.
    """

    RELEVANT = "RELEVANT"
    NOT_RELEVANT = "NOT_RELEVANT"
    NOT_INTERESTED = "NOT_INTERESTED"


class ProficiencyLevel(StrEnum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class ExperienceLevel(StrEnum):
    INTERN = "INTERN"
    ENTRY = "ENTRY"
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    LEAD = "LEAD"
    PRINCIPAL = "PRINCIPAL"


class EducationLevel(StrEnum):
    """Ordered from least to most advanced.

    The education dimension of the ranking formula compares these ordinally
    (ml.md section 4.1), so declaration order is significant — see `rank` below.
    """

    NONE = "NONE"
    HIGH_SCHOOL = "HIGH_SCHOOL"
    DIPLOMA = "DIPLOMA"
    BACHELORS = "BACHELORS"
    MASTERS = "MASTERS"
    DOCTORATE = "DOCTORATE"

    @property
    def rank(self) -> int:
        """Ordinal position, for comparing a candidate against a requirement.

        Defined explicitly rather than relying on definition order so that
        reordering the members cannot silently change ranking behaviour.
        """
        return _EDUCATION_RANK[self]


_EDUCATION_RANK: dict[EducationLevel, int] = {
    EducationLevel.NONE: 0,
    EducationLevel.HIGH_SCHOOL: 1,
    EducationLevel.DIPLOMA: 2,
    EducationLevel.BACHELORS: 3,
    EducationLevel.MASTERS: 4,
    EducationLevel.DOCTORATE: 5,
}


class WorkMode(StrEnum):
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"


class EmploymentType(StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    INTERNSHIP = "INTERNSHIP"
    TEMPORARY = "TEMPORARY"


class JobSource(StrEnum):
    """Where a job row came from.

    Kept because provenance changes how much a row is trusted: a user paste is
    one person's copy of a posting and may be truncated or edited, while an
    imported dataset row is uniform and carries an `external_id` that makes
    re-import idempotent (US-3.3 AC1).

    PARTNER_API is also half the dedup key — `ux_jobs_external` is
    `(source, external_id)` — which is what keeps one provider's ids out of
    another's namespace and makes "remove everything from provider X, their
    terms changed" a single DELETE. A licensing obligation that cannot be
    expressed as a query is a liability (ADR-019).
    """

    USER_SUBMITTED = "USER_SUBMITTED"
    DATASET_IMPORT = "DATASET_IMPORT"
    PARTNER_API = "PARTNER_API"


class JobStatus(StrEnum):
    """Whether a job takes part in ranking.

    DUPLICATE rows are retained rather than deleted: an application references
    the job it was submitted against, and deleting the loser of a dedup would
    invalidate that record (database.md section 3.3).

    No EXPIRED member yet — expiry is a fact about `expires_at`, and browse
    filters on the timestamp directly. A status value would be a second source
    of truth that something has to keep in step.
    """

    ACTIVE = "ACTIVE"
    DUPLICATE = "DUPLICATE"


class SkillRequirement(StrEnum):
    """How much a job needs a skill.

    REQUIRED weighs more than PREFERRED in the skill dimension of the ranking
    formula (ml.md section 4.1), so the distinction has to survive extraction
    rather than being flattened into "mentioned".
    """

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class SalaryPeriod(StrEnum):
    """The unit a salary figure is quoted in.

    A native enum rather than the free TEXT column database.md section 3.3
    sketches: it is a closed vocabulary like every sibling here, and the salary
    dimension of the ranking formula cannot compare two figures without knowing
    their periods agree.
    """

    YEARLY = "YEARLY"
    MONTHLY = "MONTHLY"
    HOURLY = "HOURLY"


class ApplicationStatus(StrEnum):
    """What the user has done about a job.

    Two members, not the seven database.md section 3.7 sketches. The rest of the
    lifecycle — ASSESSMENT, INTERVIEW, OFFER, REJECTED, WITHDRAWN — arrives with
    the funnel that reads them and the `application_events` log that records the
    transitions (US-7.1 AC2), rather than sitting here as five values nothing can
    set. Same rule as this module's opening note; same precedent as JobStatus
    shipping without EXPIRED and SkillRequirement without NICE_TO_HAVE.

    APPLIED is always the user's own assertion. Auto-submitting applications is
    out of scope (requirements.md section 3), so nothing infers this and nothing
    may claim it on the user's behalf.
    """

    SAVED = "SAVED"
    APPLIED = "APPLIED"
