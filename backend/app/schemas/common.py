"""Shared response schemas.

Kept separate from ORM models on purpose (ADR-004): a combined class leaks
`password_hash` the moment someone adds it to the model and forgets the response
side. Explicit read schemas make exposure a decision rather than a default.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable constant.")
    message: str = Field(description="Human-readable text. May be reworded at any time.")
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(
        default=None, description="Matches the structured log entry for this request."
    )


class ErrorResponse(BaseModel):
    """The single error envelope used by every non-2xx response (api.md 1.4)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "RESOURCE_NOT_FOUND",
                    "message": "Resume not found.",
                    "details": {},
                    "correlation_id": "01927b3e-9c4a-7f21-8e3d-2b1a5c8f9d47",
                }
            }
        }
    )

    error: ErrorDetail


class MessageResponse(BaseModel):
    """For endpoints whose only meaningful output is that they succeeded."""

    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    """Dependency-aware readiness (api.md 2.12).

    Separate from liveness: if the liveness probe checked the database, a brief
    database blip would cause the platform to kill healthy containers, turning a
    recoverable problem into an outage.
    """

    status: str
    checks: dict[str, dict[str, Any]]
