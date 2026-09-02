"""Health and readiness endpoints (api.md section 2.12)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.core.database import check_database_health
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["system"])

API_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Is the process alive?

    Checks no dependencies, on purpose. If this touched the database, a brief
    database blip would make the platform kill and restart otherwise-healthy
    containers, converting a recoverable problem into an outage.
    """
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        environment=settings.environment.value,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"description": "One or more dependencies are unavailable"}},
)
async def readiness(response: Response) -> ReadinessResponse:
    """Can this instance actually serve traffic?

    Reports each dependency individually and returns 503 when any is down, so a
    failing probe says *which* dependency failed rather than just that something
    did.
    """
    checks = {"database": await check_database_health()}

    # Redis is not wired up until Phase 10; reporting it as "ok" now would be a
    # lie, and omitting it silently would hide that it is unchecked.
    checks["redis"] = {"status": "not_configured"}

    degraded = any(check.get("status") == "error" for check in checks.values())
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(status="error" if degraded else "ok", checks=checks)
