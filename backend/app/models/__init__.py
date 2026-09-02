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
    UserRole,
    WorkMode,
)
from app.models.profile import Profile
from app.models.user import RefreshToken, User

__all__ = [
    "AuthProvider",
    "Base",
    "CreatedAtMixin",
    "EducationLevel",
    "EmploymentType",
    "ExperienceLevel",
    "Profile",
    "RefreshToken",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserRole",
    "WorkMode",
]
