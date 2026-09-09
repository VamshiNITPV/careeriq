"""Deterministic offline embeddings, for tests and a local walkthrough.

**Not noise seeded by a hash.** Two documents that share words must come out
closer than two that share none, because that is the property every test of
`/jobs/{id}/similar` actually asserts on — that a backend job is a nearer
neighbour to another backend job than to a nursing one. A fake with random
directions would force each test to hard-code its own vectors, which tests the
fixture rather than the query.

The construction is the hashing trick: each token increments one coordinate
chosen by a stable hash of the token, then the vector is L2-normalised. Two
documents' cosine is then a normalised count of shared tokens. Cheap, exactly
reproducible across processes and machines, and no model anywhere.
"""

from __future__ import annotations

import hashlib
import math
import re

from app.integrations.embeddings.base import Vector

_TOKEN = re.compile(r"[a-z0-9+#.]+")


def _hash_vector(text: str, dimensions: int) -> Vector:
    """A unit vector whose direction is determined by the words in `text`."""
    counts = [0.0] * dimensions
    for token in _TOKEN.findall(text.lower()):
        # blake2b rather than md5: ruff's bandit rules flag the latter (S324)
        # even for a non-security use like this one.
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        counts[int.from_bytes(digest, "big") % dimensions] += 1.0

    norm = math.sqrt(sum(value * value for value in counts))
    if norm == 0.0:
        # Never return all zeros. `<=>` against a zero vector is NaN, and a NaN
        # in an ORDER BY silently produces a nonsense ordering rather than an
        # error — the worst way for this to fail.
        counts[0] = 1.0
        return counts
    return [value / norm for value in counts]


class FakeEmbeddingProvider:
    """A provider that needs no model, no network and no GPU.

    The call counter is how a test proves work was *skipped* — that a second
    indexing pass over unchanged text called `embed` zero times. Asserting on
    the row's timestamp could not tell "skipped" from "recomputed the same
    answer", which is the whole point of the hash.
    """

    def __init__(
        self,
        *,
        dimensions: int = 768,
        overrides: dict[str, Vector] | None = None,
    ) -> None:
        self._dimensions = dimensions
        #: For the rare test that wants exact geometry — proving a similarity
        #: floor excludes a neighbour, say — rather than merely an ordering.
        self._overrides = overrides or {}
        self.calls = 0
        self.texts: list[str] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-hashing-trick"

    @property
    def model_version(self) -> str:
        return "v1"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[Vector]:
        self.calls += 1
        self.texts.extend(texts)
        return [self._overrides.get(text) or _hash_vector(text, self._dimensions) for text in texts]
