"""FastAPI application factory, middleware, and exception handling."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.database import dispose_engine
from app.core.exceptions import CareerIQError, build_error_body
from app.core.ids import uuid7
from app.core.logging import configure_logging, correlation_id_var, get_logger

log = get_logger(__name__)

CORRELATION_HEADER = "X-Correlation-ID"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    log.info(
        "application starting",
        environment=settings.environment.value,
        debug=settings.debug,
    )

    # Seed the skill taxonomy. Idempotent (ON CONFLICT DO NOTHING), so running
    # it on every start is safe and means a fresh database is usable without a
    # separate manual step. Failure is logged, not fatal: the API still serves
    # everything that does not depend on the taxonomy.
    try:
        from app.core.database import get_session_factory
        from app.services.resume.pipeline import seed_skill_taxonomy

        async with get_session_factory()() as session:
            await seed_skill_taxonomy(session)
    except Exception as exc:
        log.error("skill taxonomy seeding failed", error=str(exc))

    yield

    # Return pooled connections deliberately instead of letting the process exit
    # drop them, which leaves sockets in the database's connection table until
    # they time out.
    await dispose_engine()
    log.info("application stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton so tests can construct an app
    with overridden settings without re-importing the module.
    """
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        description=(
            "AI Career Intelligence & Job Optimization Platform. "
            "See docs/api.md for design rationale."
        ),
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs are useful in development and an information
        # disclosure surface in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    _register_middleware(app, settings)
    _register_exception_handlers(app, settings)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


# ---------------------------------------------------------------- middleware
def _register_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def correlation_and_timing(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        """Assign a correlation id and record request timing.

        An inbound X-Correlation-ID is honoured so a trace can span services;
        otherwise one is generated. The id goes into a ContextVar, which
        propagates across await boundaries into background tasks — that is what
        makes a resume upload traceable from request to worker completion
        (architecture.md section 4).
        """
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid7())
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[CORRELATION_HEADER] = correlation_id
        response.headers["X-Response-Time-ms"] = str(duration_ms)

        # Health checks run constantly and would drown out real traffic.
        if not request.url.path.endswith("/health"):
            log.info(
                "request completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        return response

    # Explicit allow-list, never "*" alongside credentials (ADR-014). A wildcard
    # with credentials lets any origin drive an authenticated session.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", CORRELATION_HEADER],
        expose_headers=[CORRELATION_HEADER, "X-Response-Time-ms"],
    )


# ---------------------------------------------------------------- error handling
def _register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    """Map every failure onto the single error envelope (api.md section 1.4).

    Without these, three different response shapes would reach clients:
    FastAPI's `{"detail": ...}`, Pydantic's validation array, and an HTML 500.
    """

    @app.exception_handler(CareerIQError)
    async def handle_app_error(request: Request, exc: CareerIQError) -> JSONResponse:
        log.info(
            "application error",
            code=exc.code,
            status_code=exc.status_code,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_body(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                correlation_id=correlation_id_var.get(),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Field errors are safe to return — they describe the caller's own input.
        # `input` is dropped so a rejected password is never echoed back.
        fields = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            # Literal rather than the Starlette constant: the name for 422 was
            # renamed (ENTITY -> CONTENT) and the old alias now warns. The
            # number is stable across versions.
            status_code=422,
            content=build_error_body(
                code="VALIDATION_ERROR",
                message="The request contains invalid data.",
                details={"fields": fields},
                correlation_id=correlation_id_var.get(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Covers framework-raised errors such as 404 for an unknown route and
        # 405 for a wrong method, keeping them in the same envelope.
        codes = {
            404: "RESOURCE_NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            403: "PERMISSION_DENIED",
            401: "AUTHENTICATION_FAILED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_body(
                code=codes.get(exc.status_code, "HTTP_ERROR"),
                message=str(exc.detail),
                correlation_id=correlation_id_var.get(),
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Anything reaching here is a bug. The detail goes to the logs; the
        # client gets an opaque message plus the correlation id that ties their
        # report to the log entry (ADR-014).
        log.exception(
            "unhandled exception",
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
        )
        content = build_error_body(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            details={"error": str(exc)} if settings.debug else {},
            correlation_id=correlation_id_var.get(),
        )
        return JSONResponse(status_code=500, content=content)


app = create_app()
