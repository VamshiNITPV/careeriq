"""Shared FastAPI dependencies.

Wiring only. Anything here that starts making decisions belongs in a service.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.exceptions import (
    AuthenticationError,
    InvalidTokenError,
    PermissionDeniedError,
)
from app.core.security import decode_access_token
from app.integrations.email import get_email_provider
from app.integrations.storage import ObjectStorage, get_object_storage
from app.models.user import User
from app.repositories.career import (
    CareerEntityRepository,
    CertificationRepository,
    EducationRepository,
    ProjectRepository,
    WorkExperienceRepository,
)
from app.repositories.job import CompanyRepository, JobRepository, JobSkillRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.resume import ResumeRepository, ResumeVersionRepository
from app.repositories.skill import CandidateSkillRepository, SkillRepository
from app.repositories.user import ProfileRepository, UserRepository
from app.repositories.verification import VerificationTokenRepository
from app.services.auth import AuthService
from app.services.job.service import JobService
from app.services.notifications import NotificationService
from app.services.profile import ProfileService
from app.services.resume.pipeline import process_resume_version
from app.services.resume.service import ResumeService

# auto_error=False so a missing header raises our own AuthenticationError and
# produces the standard error envelope, rather than FastAPI's default 403 body
# which would be the one response in the API with a different shape.
_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------- repositories
def get_user_repository(session: DbSession) -> UserRepository:
    return UserRepository(session)


def get_profile_repository(session: DbSession) -> ProfileRepository:
    return ProfileRepository(session)


def get_refresh_token_repository(session: DbSession) -> RefreshTokenRepository:
    return RefreshTokenRepository(session)


def get_verification_token_repository(session: DbSession) -> VerificationTokenRepository:
    return VerificationTokenRepository(session)


# ---------------------------------------------------------------- services
def get_notification_service() -> NotificationService:
    # The provider is chosen by configuration and cached per process; tests
    # override this dependency with a capturing provider.
    return NotificationService(get_email_provider())


def get_auth_service(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    profiles: Annotated[ProfileRepository, Depends(get_profile_repository)],
    refresh_tokens: Annotated[RefreshTokenRepository, Depends(get_refresh_token_repository)],
    verification_tokens: Annotated[
        VerificationTokenRepository, Depends(get_verification_token_repository)
    ],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
) -> AuthService:
    return AuthService(
        users=users,
        profiles=profiles,
        refresh_tokens=refresh_tokens,
        verification_tokens=verification_tokens,
        notifications=notifications,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# ---------------------------------------------------------------- resumes
def get_resume_repository(session: DbSession) -> ResumeRepository:
    return ResumeRepository(session)


def get_resume_version_repository(session: DbSession) -> ResumeVersionRepository:
    return ResumeVersionRepository(session)


def get_skill_repository(session: DbSession) -> SkillRepository:
    return SkillRepository(session)


def get_candidate_skill_repository(session: DbSession) -> CandidateSkillRepository:
    return CandidateSkillRepository(session)


def get_job_repository(session: DbSession) -> JobRepository:
    return JobRepository(session)


def get_company_repository(session: DbSession) -> CompanyRepository:
    return CompanyRepository(session)


def get_job_skill_repository(session: DbSession) -> JobSkillRepository:
    return JobSkillRepository(session)


def get_job_service(
    jobs: Annotated[JobRepository, Depends(get_job_repository)],
    companies: Annotated[CompanyRepository, Depends(get_company_repository)],
    job_skills: Annotated[JobSkillRepository, Depends(get_job_skill_repository)],
    skills: Annotated[SkillRepository, Depends(get_skill_repository)],
) -> JobService:
    return JobService(jobs=jobs, companies=companies, job_skills=job_skills, skills=skills)


def get_storage() -> ObjectStorage:
    # Overridden in tests with a temporary directory, so the suite never writes
    # into a real upload location.
    return get_object_storage()


def get_career_repositories(session: DbSession) -> list[CareerEntityRepository[Any]]:
    """Every entity type a resume can produce.

    One list rather than four dependencies, because the only caller treats them
    identically — and a fifth entity type should be one line here, not five
    edits across the wiring.
    """
    return [
        WorkExperienceRepository(session),
        EducationRepository(session),
        ProjectRepository(session),
        CertificationRepository(session),
    ]


def get_resume_service(
    resumes: Annotated[ResumeRepository, Depends(get_resume_repository)],
    versions: Annotated[ResumeVersionRepository, Depends(get_resume_version_repository)],
    storage: Annotated[ObjectStorage, Depends(get_storage)],
    candidate_skills: Annotated[CandidateSkillRepository, Depends(get_candidate_skill_repository)],
    career: Annotated[list[CareerEntityRepository[Any]], Depends(get_career_repositories)],
) -> ResumeService:
    return ResumeService(
        resumes=resumes,
        versions=versions,
        storage=storage,
        candidate_skills=candidate_skills,
        career=career,
    )


ResumeServiceDep = Annotated[ResumeService, Depends(get_resume_service)]


# ---------------------------------------------------------------- profile
def get_profile_service(
    profiles: Annotated[ProfileRepository, Depends(get_profile_repository)],
) -> ProfileService:
    return ProfileService(profiles=profiles)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


async def run_resume_pipeline(version_id: uuid.UUID) -> None:
    """Background entry point for parsing an uploaded resume.

    A dependency rather than a direct call so tests can replace it. Otherwise
    every upload test schedules a real background task that runs on the global
    engine, cannot see the test's uncommitted rows, and logs an ERROR — noise
    that would eventually hide a genuine failure.
    """
    await process_resume_version(version_id)


def get_pipeline_runner() -> Callable[[uuid.UUID], Awaitable[None]]:
    return run_resume_pipeline


PipelineRunnerDep = Annotated[Callable[[uuid.UUID], Awaitable[None]], Depends(get_pipeline_runner)]
SkillRepositoryDep = Annotated[SkillRepository, Depends(get_skill_repository)]
ResumeVersionRepositoryDep = Annotated[
    ResumeVersionRepository, Depends(get_resume_version_repository)
]
CandidateSkillRepositoryDep = Annotated[
    CandidateSkillRepository, Depends(get_candidate_skill_repository)
]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
JobSkillRepositoryDep = Annotated[JobSkillRepository, Depends(get_job_skill_repository)]


# ---------------------------------------------------------------- current user
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    """Resolve the authenticated user from the bearer token.

    The database lookup on every request is deliberate. A JWT alone would be
    cheaper, but it cannot express that an account was deactivated or deleted a
    minute ago — the token stays valid for its full 30 minutes. Access tokens
    are short-lived precisely so this stays a single indexed primary-key read.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication credentials were not provided.")

    payload = decode_access_token(credentials.credentials)

    user = await users.get(payload.subject)
    if user is None:
        # Signature was valid but the account is gone. Same error as a bad
        # token: the client's remedy is identical either way.
        raise InvalidTokenError()

    if not user.is_active:
        raise AuthenticationError("This account is not active.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    """Role gate for admin-only routes.

    403 is correct here, unlike ownership checks which must return 404: the
    caller already knows the endpoint exists, so there is nothing to leak
    (api.md section 1.3).
    """
    if not user.is_admin:
        raise PermissionDeniedError()
    return user


AdminUser = Annotated[User, Depends(require_admin)]


# ---------------------------------------------------------------- request context
def get_client_ip(request: Request) -> str | None:
    """Best-effort client IP for the refresh token audit trail.

    X-Forwarded-For is trusted only because the app sits behind a known proxy
    (Cloud Run). Exposed directly it is client-controlled and must not be used
    for anything security-critical — here it is audit metadata, not a control.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
