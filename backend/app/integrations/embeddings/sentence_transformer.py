"""The real adapter — the only module in this repository that imports torch.

Nothing in the API's import path reaches this file: `get_embedding_provider()`
imports it inside the function body, and only when EMBEDDING_PROVIDER says so.
The API image does not even install torch (see requirements-ml.txt), so an
accidental import there fails loudly rather than costing seconds of cold start
silently. `tests/unit/test_embedding_provider.py` asserts that separation.
"""

from __future__ import annotations

from typing import Any

import anyio
import anyio.to_thread
from anyio import CapacityLimiter

from app.core.logging import get_logger
from app.integrations.embeddings.base import EmbeddingProviderError, Vector

log = get_logger(__name__)

#: One encode at a time, and this is correctness rather than throughput.
#:
#: The model is a single shared object whose `encode` is not documented as
#: thread-safe, and torch already saturates the CPU inside one forward pass — so
#: two concurrent batches are both slower than two sequential ones *and* race.
#: anyio's default thread limiter is 40, which would allow exactly that.
_LIMITER = CapacityLimiter(1)


class SentenceTransformerProvider:
    """Local CPU inference: no API cost, no rate limit, deterministic (ml.md §3.1)."""

    def __init__(self, *, model_name: str, model_version: str, threads: int) -> None:
        self._model_name = model_name
        self._model_version = model_version
        self._threads = threads
        #: Loaded on first use, not in __init__. A worker whose backlog is empty
        #: never pays the ~420 MB of resident memory, and the import itself —
        #: several seconds — happens on a worker thread rather than the loop.
        self._model: Any | None = None

    @property
    def name(self) -> str:
        return "sentence_transformers"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def dimensions(self) -> int:
        model = self._load()
        # get_sentence_embedding_dimension was renamed to get_embedding_dimension
        # and now warns. Both are tried rather than pinning a version, because
        # this one call is the only place the rename touches us and the model is
        # otherwise version-tolerant.
        getter = getattr(model, "get_embedding_dimension", None) or (
            model.get_sentence_embedding_dimension
        )
        return int(getter())

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            # Left to itself torch spawns one thread per core. On a laptop also
            # running Postgres, Vite and a browser that starves everything else
            # and, for batches this small, is measurably slower than one or two.
            torch.set_num_threads(self._threads)
            log.info("loading embedding model", model=self._model_name)
            self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    async def embed(self, texts: list[str]) -> list[Vector]:
        """Reconcile ADR-007's async interface with a synchronous, CPU-bound model.

        `to_thread` rather than pretending: the encode call blocks for tens to
        hundreds of milliseconds per batch, and on the event loop that stalls
        every other request in the process for its whole duration.

        A thread is not a no-op for CPU-bound Python because of the GIL — but
        torch releases the GIL inside its C++ kernels, which is where
        essentially all of this time goes, so the loop genuinely gets to run.
        """
        if not texts:
            return []
        try:
            return await anyio.to_thread.run_sync(self._encode, texts, limiter=_LIMITER)
        except Exception as exc:
            raise EmbeddingProviderError(f"{type(exc).__name__}: {exc}") from exc

    def _encode(self, texts: list[str]) -> list[Vector]:
        model = self._load()
        # normalize_embeddings is what makes `1 - (a <=> b)` the cosine
        # similarity, which the whole search query depends on.
        vectors = model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [[float(value) for value in row] for row in vectors]
