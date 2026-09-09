"""Embeddings, behind a provider interface (ADR-007)."""

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderError,
    Vector,
)
from app.integrations.embeddings.fake import FakeEmbeddingProvider

log = get_logger(__name__)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "FakeEmbeddingProvider",
    "Vector",
    "get_embedding_provider",
]


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider | None:
    """Build the configured provider once per process, or None if there is none.

    Caching the object is what makes the model load once rather than per call —
    it holds ~420 MB of weights after first use, so a fresh instance per request
    would be ruinous.

    **The `sentence_transformers` import is inside the branch, deliberately.**
    Importing torch costs several seconds and hundreds of megabytes of resident
    memory, and the API never needs it: it compares vectors in SQL. Keeping the
    import here is what lets the same source tree run in an API image that does
    not even install torch (architecture.md's cold-start risk).

    `None` rather than a fallback, matching `get_job_provider`. An unconfigured
    embedder means no vectors are produced and `/similar` says so; it does not
    mean silently substituting something else.
    """
    settings = get_settings()

    if settings.embedding_provider == "sentence_transformers":
        from app.integrations.embeddings.sentence_transformer import (
            SentenceTransformerProvider,
        )

        return SentenceTransformerProvider(
            model_name=settings.embedding_model,
            model_version=settings.embedding_model_version,
            threads=settings.embedding_threads,
        )

    if settings.embedding_provider == "fake":
        log.warning("embedding provider is 'fake' — vectors are SYNTHETIC, not model output")
        return FakeEmbeddingProvider(dimensions=settings.embedding_dimensions)

    return None
