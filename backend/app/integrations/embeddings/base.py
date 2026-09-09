"""Embedding provider interface (ADR-007).

The same shape as the jobs and email packages beside it: services depend on the
Protocol, concrete adapters are chosen by configuration, and tests use a fake.

**Which model produced a vector never crosses this interface.** It is recorded
on the row instead, as `model_name` and `model_version`, because changing models
invalidates every stored vector and the two generations have to coexist while a
backfill runs. A provider that only returned floats would make that impossible.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

#: One embedding.
#:
#: A plain list rather than a numpy array: it crosses into SQL as a literal and
#: into JSON in the evaluation scripts, and neither wants an ndarray.
type Vector = list[float]


class EmbeddingProviderError(RuntimeError):
    """Any failure to produce vectors.

    Deliberately not a taxonomy, for the reason `JobProviderError` gives: every
    caller makes the same decision on it — skip this batch, log, try again on
    the next tick — so a missing model file, an out-of-memory kill and a
    malformed input all collapse here.
    """


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str:
        """Short, stable identifier for logs. Not what is stored on the row."""
        ...

    @property
    def model_name(self) -> str:
        """Written to every row this provider produces.

        Changing it orphans every vector already stored under the old name —
        which is the point. Old and new coexist under the unique key rather than
        being silently mixed, so search keeps working while a backfill runs.
        """
        ...

    @property
    def model_version(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[Vector]:
        """Embed a batch. Order-preserving: `result[i]` belongs to `texts[i]`.

        `async` per ADR-007, though every implementation is CPU-bound and
        synchronous. Reconciling those is the *adapter's* job, not the caller's
        — see `sentence_transformer.py`.

        **Returns L2-normalised vectors.** Not an implementation detail: cosine
        distance is only well-conditioned on normalised vectors, and it is what
        lets `1 - (a <=> b)` be read directly as the cosine similarity.
        """
        ...
