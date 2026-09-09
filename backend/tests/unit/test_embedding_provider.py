"""The provider contract, and the boundary that keeps torch out of the API."""

from __future__ import annotations

import math
import subprocess
import sys

import pytest

from app.integrations.embeddings import FakeEmbeddingProvider
from app.services.embedding.documents import (
    DOCUMENT_VERSION,
    MIN_CONTENT_CHARS,
    document_hash,
    is_embeddable,
)


def test_the_api_import_path_carries_no_ml_dependencies() -> None:
    """architecture.md's risk table: keep ML models out of the API's import path.

    Asserted rather than commented, because the failure mode is silent — one
    stray top-level `import torch` in a service adds seconds and hundreds of
    megabytes to every cold start, and nothing anywhere goes red.

    A subprocess, not an in-process check on sys.modules: pytest has already
    imported half the application by the time any test runs, and something else
    in the suite may legitimately import the real provider.
    """
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.main, sys;"
            "assert 'torch' not in sys.modules, 'torch reached the API import path';"
            "assert 'sentence_transformers' not in sys.modules,"
            " 'sentence_transformers reached the API import path'",
        ],
        check=True,
    )


class TestFakeProvider:
    """The fake has to be *meaningfully* deterministic, not merely repeatable.

    Every test of `/jobs/{id}/similar` asserts on ordering, so documents that
    share words must come out closer than documents that do not. Seeded noise
    would make those assertions coin flips that each test had to hard-code
    around — testing the fixture rather than the query.
    """

    async def test_is_reproducible_across_instances(self) -> None:
        first = await FakeEmbeddingProvider().embed(["python backend engineer"])
        second = await FakeEmbeddingProvider().embed(["python backend engineer"])

        assert first == second

    async def test_shared_words_are_nearer_than_unrelated_ones(self) -> None:
        provider = FakeEmbeddingProvider()
        vectors = await provider.embed(
            [
                "python backend engineer fastapi postgresql",
                "backend engineer python django postgresql",
                "registered nurse paediatric ward night shift",
            ]
        )

        def cosine(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        assert cosine(vectors[0], vectors[1]) > cosine(vectors[0], vectors[2])

    async def test_returns_unit_vectors(self) -> None:
        # Cosine distance is only well-conditioned on normalised vectors, and
        # `1 - (a <=> b)` is only the similarity if they are.
        (vector,) = await FakeEmbeddingProvider().embed(["python"])

        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)

    async def test_never_returns_a_zero_vector(self) -> None:
        # `<=>` against a zero vector is NaN, and a NaN in an ORDER BY produces
        # a nonsense ordering rather than an error — the worst way to fail.
        (vector,) = await FakeEmbeddingProvider().embed(["!!! ???"])

        assert any(value != 0.0 for value in vector)

    async def test_counts_calls_so_a_test_can_prove_work_was_skipped(self) -> None:
        provider = FakeEmbeddingProvider()

        await provider.embed(["a"])
        await provider.embed(["b"])

        assert provider.calls == 2

    async def test_an_empty_batch_costs_nothing(self) -> None:
        provider = FakeEmbeddingProvider()

        assert await provider.embed([]) == []


class TestDocumentHash:
    def test_the_document_version_is_part_of_the_hash(self) -> None:
        """Changing how a document is built must invalidate every stored hash.

        Without the marker, unchanged source text would keep a vector built from
        a now-different document — a corpus-wide inconsistency with no symptom
        until the rankings look wrong.
        """
        document = "Title: Backend Engineer"

        assert document_hash(document) != hash_without_version(document)

    def test_is_stable_for_the_same_text(self) -> None:
        assert document_hash("Title: X") == document_hash("Title: X")

    def test_differs_for_different_text(self) -> None:
        assert document_hash("Title: X") != document_hash("Title: Y")


def hash_without_version(document: str) -> str:
    import hashlib

    return hashlib.sha256(document.encode()).hexdigest()


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("", False),
        ("Title: Engineer", False),
        # Built from the constant rather than written out. A hand-typed string
        # lands on the wrong side of the boundary by one character sooner or
        # later — mine did, by exactly one — and then the case asserts something
        # nobody intended.
        ("x" * (MIN_CONTENT_CHARS - 1), False),
        ("x" * MIN_CONTENT_CHARS, True),
    ],
)
def test_a_document_must_carry_enough_to_embed(document: str, expected: bool) -> None:
    # A near-empty document produces a vector that is mostly noise, and it would
    # sit in the corpus looking like a plausible neighbour for anything at all.
    assert is_embeddable(document) is expected


def test_document_version_is_recorded() -> None:
    # Named so a reviewer notices it has to be bumped when the shape changes.
    assert DOCUMENT_VERSION
