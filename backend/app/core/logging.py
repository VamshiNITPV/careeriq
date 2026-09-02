"""Structured logging with request correlation.

Architecture.md §4 requires JSON logs carrying a correlation id that follows a
request from HTTP handler into background workers, so a resume upload can be
traced end to end. That id lives in a ContextVar rather than being threaded
through every function signature — ContextVars propagate correctly across
`await` boundaries and into asyncio tasks, which is exactly the lifetime we need.

Local development uses a human-readable renderer; deployed environments emit
JSON (LOG_JSON=true, enforced for production in config).
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# Set per request by CorrelationIdMiddleware; read by the processor below.
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def add_correlation_id(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Attach the current request's correlation id to every log line."""
    cid = correlation_id_var.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


# Fields that must never reach a log sink, at any level (ADR-014).
_REDACTED_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "jwt_secret_key",
        "api_key",
        "secret",
    }
)


def redact_sensitive(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Replace sensitive values with a marker.

    This is a safety net, not a licence to log credentials. Call sites should not
    pass these fields at all; this catches the ones that slip through, which in a
    codebase of any size is not a hypothetical.
    """
    for key in list(event_dict):
        if key.lower() in _REDACTED_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog and route stdlib logging through it.

    Routing stdlib logging matters: SQLAlchemy, uvicorn and asyncpg all use the
    stdlib logger. Without this, half the output would be structured and half
    would be plain text.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_correlation_id,
        redact_sensitive,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; clear them so output is not duplicated.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # SQLAlchemy echoes every statement at INFO, which is overwhelming.
    # DATABASE_ECHO controls that separately.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Prefer module-level: log = get_logger(__name__)."""
    return structlog.stdlib.get_logger(name)
