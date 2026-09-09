"""SQLAlchemy ORM models. No business logic (architecture.md section 2).

Every model must be imported here. Alembic's autogenerate compares the database
against `Base.metadata`, and a model that is never imported is not registered on
that metadata — so autogenerate silently emits a migration that drops its table.
Importing here makes `from app.models import Base` sufficient to see everything.
"""

from pgvector.sqlalchemy import Vector as _Vector
from sqlalchemy.dialects.postgresql.base import ischema_names as _pg_ischema_names

from app.models.application import Application
from app.models.base import (
    Base,
    CreatedAtMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.career import Certification, EducationRecord, Project, WorkExperience
from app.models.embedding import CandidateEmbedding, JobEmbedding
from app.models.enums import (
    ApplicationStatus,
    AuthProvider,
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    JobSource,
    JobStatus,
    ProcessingStatus,
    ProficiencyLevel,
    RecommendationFeedback,
    SalaryPeriod,
    SkillRequirement,
    UserRole,
    VerificationPurpose,
    WorkMode,
)
from app.models.job import Company, Job, JobSkill
from app.models.job_fetch import JobFetchRun
from app.models.profile import Profile
from app.models.recommendation import RecommendationFeedbackRow
from app.models.resume import Resume, ResumeVersion
from app.models.skill import CandidateSkill, Skill
from app.models.user import RefreshToken, User
from app.models.verification import VerificationToken

# Teach the PostgreSQL dialect about `vector`, so reflection returns the real
# type rather than NullType.
#
# `env.py` sets compare_type=True, and without this Alembic reflects an
# embedding column as NullType and reports a phantom type change on every
# `alembic check` run, forever. A check that is always dirty is one nobody
# reads, which costs more than the drift it was meant to catch.
_pg_ischema_names.setdefault("vector", _Vector)


__all__ = [
    "Application",
    "ApplicationStatus",
    "AuthProvider",
    "Base",
    "CandidateEmbedding",
    "CandidateSkill",
    "Certification",
    "Company",
    "CreatedAtMixin",
    "EducationLevel",
    "EducationRecord",
    "EmploymentType",
    "ExperienceLevel",
    "Job",
    "JobEmbedding",
    "JobFetchRun",
    "JobSkill",
    "JobSource",
    "JobStatus",
    "ProcessingStatus",
    "ProficiencyLevel",
    "Profile",
    "Project",
    "RecommendationFeedback",
    "RecommendationFeedbackRow",
    "RefreshToken",
    "Resume",
    "ResumeVersion",
    "SalaryPeriod",
    "Skill",
    "SkillRequirement",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserRole",
    "VerificationPurpose",
    "VerificationToken",
    "WorkExperience",
    "WorkMode",
]
