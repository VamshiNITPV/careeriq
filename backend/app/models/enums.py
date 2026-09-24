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

    # S105 flags any assignment to a name containing "password" as a hardcoded
    # credential. These are enum labels, not secrets.
    #
    # Worded to avoid opening with the directive word itself: ruff read the
    # previous phrasing as a malformed `noqa` and warned on every run.
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

    The full lifecycle, completed 2026-09-16 with US-7.1. It shipped as two
    members under US-7.0 and the other five waited for the event log that
    records moving between them — a status nothing can set is worse than a
    status that does not exist.

    Ordered as the funnel runs. SAVED through OFFER are **active**; REJECTED and
    WITHDRAWN are where an application stops. US-7.1 AC1 asks for exactly this:
    a forward chain, with the two endings reachable from any active state.

    APPLIED is always the user's own assertion. Auto-submitting applications is
    out of scope (requirements.md section 3), so nothing infers this and nothing
    may claim it on the user's behalf. The same holds for every stage past it:
    an employer's reply is something the user tells us about, never something we
    conclude.
    """

    SAVED = "SAVED"
    APPLIED = "APPLIED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationEventType(StrEnum):
    """What an `application_events` row records (US-7.1 AC2).

    One member for now. `NOTE_ADDED` and `INTERVIEW_SCHEDULED` are sketched in
    database.md section 3.7 and wait for notes and a scheduler to exist, on the
    same rule as the statuses above.
    """

    STATUS_CHANGE = "STATUS_CHANGE"


class AnalysisStatus(StrEnum):
    """Where one resume-optimization run has got to (US-6.1).

    `POST /optimize/analyze` answers 202 and the work happens outside the
    request, so the row exists before there is anything in it. Without a status
    the caller cannot tell "still thinking" from "finished with nothing to say",
    and those need different screens.

    FAILED always carries a reason, for the same reason `ProcessingStatus` does:
    a run that stops with no explanation is unusable to the user and to whoever
    debugs it.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class SuggestionDecision(StrEnum):
    """What the user did with one suggestion (US-6.1 AC1).

    PENDING rather than a nullable column: "not looked at yet" is a real state
    the review screen has to render, and a null would make it indistinguishable
    from data that failed to load.

    REJECTED is kept rather than deleted. A rejected suggestion is evidence the
    user was shown it and said no, which is the difference between a suggestion
    that was never made and one that was declined -- and re-offering something
    already refused is the surest way to make the feature annoying.
    """

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InterviewStatus(StrEnum):
    """Where a mock interview is (database.md section 3.8, ADR-013).

    CREATED and IN_PROGRESS are separate because they answer different
    questions. A session exists the moment the user asks for one, but nothing
    has been asked yet -- and "you have an interview waiting" is a different
    thing to show than "you are three questions in".

    ABANDONED rather than deleting the row. A half-finished interview is
    evidence: the questions asked, the answers given and their scores are all
    still true, and they are the only record of what the user was struggling
    with when they stopped.
    """

    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class QuestionDifficulty(StrEnum):
    """How hard a question is, and the axis the adaptive policy moves along.

    Four rungs, ordered. `policy.py` steps up and down this ladder in response
    to scores, which is why the order of these members is load-bearing rather
    than cosmetic -- it is read by `harder()` and `easier()` there, not merely
    displayed.
    """

    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    EXPERT = "EXPERT"


class InterviewTopicSource(StrEnum):
    """Where an interview's topics came from (US-8.1 AC1).

    Three states, and a boolean could only express two. `blueprint.py` carried
    `is_generic: bool` and had to fold "from the posting you chose" and "from
    what the role generally demands" into one value -- which are the two cases a
    candidate would most want told apart.

    Stored on the row rather than recomputed on read, the same reasoning
    `interview_scores.next_difficulty` records: the corpus grows, and a
    transcript read next month should say what its questions were actually built
    from, not what today's corpus would produce.
    """

    #: The targeted posting's own skills, weighted REQUIRED over PREFERRED.
    #: The strongest case, and the only one that can honestly be described as
    #: questions built for this job.
    THIS_JOB = "THIS_JOB"
    #: Aggregated over every live posting whose title matches the role. Real
    #: market demand, but not this employer's list.
    ROLE_DEMAND = "ROLE_DEMAND"
    #: Neither had enough to say. Not an error -- somebody may be rehearsing for
    #: a role this corpus has never carried a posting for -- but it must never be
    #: presented as demand-derived.
    GENERIC = "GENERIC"
