"""LLM access, behind a provider interface (ADR-007, ml.md section 6)."""

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.llm.base import (
    CONTEXT_CLOSE,
    CONTEXT_OPEN,
    LLMError,
    LLMProvider,
    LLMQuotaError,
    LLMResponse,
    LLMSafetyError,
    LLMUnavailableError,
    Prompt,
    sanitise_untrusted,
)
from app.integrations.llm.fake import FakeLLMProvider

log = get_logger(__name__)

__all__ = [
    "CONTEXT_CLOSE",
    "CONTEXT_OPEN",
    "FakeLLMProvider",
    "LLMError",
    "LLMProvider",
    "LLMQuotaError",
    "LLMResponse",
    "LLMSafetyError",
    "LLMUnavailableError",
    "Prompt",
    "get_llm_provider",
    "sanitise_untrusted",
]


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider | None:
    """Build the configured provider once per process, or None if there is none.

    Caching the provider *object* is safe because it holds only configuration.
    An adapter must not cache an `httpx.AsyncClient` on itself: a client binds to
    whichever event loop first touches it, and a process-cached one then fails on
    every later loop.

    `None` rather than a fallback, matching `get_job_provider`. There is no
    sensible default here: a stub that returns canned resume suggestions would
    put text in front of a user that no model produced and no validator
    meaningfully checked. Unconfigured means the AI endpoints answer 503 and say
    so, which is honest and recoverable.
    """
    settings = get_settings()

    if settings.llm_provider == "gemini":
        from app.integrations.llm.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )

    if settings.llm_provider == "fake":
        log.warning("LLM provider is 'fake' — any generated text is SYNTHETIC")
        return FakeLLMProvider(["fake provider: no model was called"])

    return None
