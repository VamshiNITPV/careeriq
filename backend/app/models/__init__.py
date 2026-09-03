"""SQLAlchemy ORM models. No business logic (architecture.md section 2).

Every model must be imported here. Alembic's autogenerate compares the database
against `Base.metadata`, and a model that is never imported is not registered on
that metadata — so autogenerate silently emits a migration that drops its table.
Importing here makes `from app.models import Base` sufficient to see everything.
"""

from app.models.base import (
    Base,
    CreatedAtMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import (
    AuthProvider,
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    JobSource,
    JobStatus,
    ProcessingStatus,
    ProficiencyLevel,
    SalaryPeriod,
    SkillRequirement,
    UserRole,
    VerificationPurpose,
    WorkMode,
)
from app.models.job import Company, Job, JobSkill
from app.models.profile import Profile
from app.models.resume import Resume, ResumeVersion
from app.models.skill import CandidateSkill, Skill
from app.models.user import RefreshToken, User
from app.models.verification import VerificationToken

__all__ = [
    "AuthProvider",
    "Base",
    "CandidateSkill",
    "Company",
    "CreatedAtMixin",
    "EducationLevel",
    "EmploymentType",
    "ExperienceLevel",
    "Job",
    "JobSkill",
    "JobSource",
    "JobStatus",
    "ProcessingStatus",
    "ProficiencyLevel",
    "Profile",
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
    "WorkMode",
]
