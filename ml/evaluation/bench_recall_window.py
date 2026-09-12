"""What a wider recall window actually costs (ADR-006, NFR-2).

    docker compose run --rm -v "$(pwd)/ml:/ml" backend \
        sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.bench_recall_window'

`RECALL_LIMIT` is the one knob that trades latency for recall: stage one hands
stage two a fixed number of postings, and everything downstream is bounded by it.
The matching evaluation says Recall@200 is 0.917 and Recall@300 is 1.000, so the
question is only what the wider window costs.

**Measured rather than extrapolated, on purpose.** The tempting arithmetic is
"200 jobs took 47.8ms, so 300 takes ~72ms". That assumes the cost is linear in
the window and that nothing else moves — neither of which is established, and
this project has been wrong about exactly that kind of guess before. The recall
query itself may not scale linearly (it is an index scan plus a join), and the
scorer does one batched fetch whose cost per row falls as the batch grows.

**What this cannot tell you.** The corpus is ~319 live jobs, so any window at or
above that returns the whole thing and the rows stop growing. Numbers past that
point measure the same work twice, not a bigger job. NFR-2's 10,000-job target is
therefore still an extrapolation from here — this settles the 200-vs-300 decision
and nothing larger.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import statistics
import time
import uuid
from decimal import Decimal

from app.core.database import get_session_factory
from app.integrations.embeddings import get_embedding_provider
from app.models.job import Job
from app.repositories.matching import MatchingRepository
from app.services.matching.recall import recall_jobs
from app.services.matching.recommend import rank_jobs
from app.services.matching.service import MatchingService
from sqlalchemy import select

DATA = pathlib.Path("/ml/datasets/matching")

#: Windows to time. 200 is shipped; 300 is what the recall sweep says clears the
#: target; the rest bracket it so the shape of the curve is visible rather than
#: inferred from two points.
WINDOWS = (50, 100, 200, 300, 500)

#: Repeats per window. Small, because each one scores the whole set against a
#: real database — enough for a median and a worst case, not a distribution.
RUNS = 7


async def time_window(
    *, session, service, provider, query: dict, limit: int
) -> tuple[float, int]:
    """One full stage-one-plus-stage-two pass, as the endpoint runs it."""
    started = time.perf_counter()

    recalled = await recall_jobs(
        session=session,
        user_id=uuid.UUID(query["user_id"]),
        resume_version_id=uuid.UUID(query["resume_version_id"]),
        model_name=provider.model_name,
        limit=limit,
        exclude_applied=True,
    )
    assert recalled is not None, "no recall — is the resume indexed?"

    ids = [row.job_id for row in recalled]
    cosines = {row.job_id: Decimal(str(row.similarity)) for row in recalled}
    by_id = {
        job.id: job for job in (await session.scalars(select(Job).where(Job.id.in_(ids)))).all()
    }
    ordered = [by_id[job_id] for job_id in ids if job_id in by_id]

    await rank_jobs(
        service=service,
        user_id=uuid.UUID(query["user_id"]),
        resume_version_id=uuid.UUID(query["resume_version_id"]),
        jobs=ordered,
        cosines=cosines,
        limit=20,
        offset=0,
    )

    return (time.perf_counter() - started) * 1000, len(ordered)


async def main() -> None:
    provider = get_embedding_provider()
    if provider is None:
        raise SystemExit("EMBEDDING_PROVIDER must be configured")

    queries = [
        json.loads(line)
        for line in (DATA / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    async with get_session_factory()() as session:
        service = MatchingService(repo=MatchingRepository(session), provider=provider)

        # One untimed pass first. Without it the *first* window measured absorbs
        # every one-off cost — connection setup, query plans, Python warming up —
        # and reports a worse maximum than windows twice its size, which reads as
        # noise in the result rather than as the artefact it is.
        for query in queries:
            await time_window(
                session=session, service=service, provider=provider, query=query, limit=max(WINDOWS)
            )

        print(f"{'window':>8}{'scored':>8}{'median ms':>12}{'worst ms':>11}  budget")
        for limit in WINDOWS:
            timings: list[float] = []
            scored = 0
            for _ in range(RUNS):
                for query in queries:
                    elapsed, count = await time_window(
                        session=session,
                        service=service,
                        provider=provider,
                        query=query,
                        limit=limit,
                    )
                    timings.append(elapsed)
                    scored = max(scored, count)

            median = statistics.median(timings)
            worst = max(timings)
            verdict = "ok" if worst < 500 else "OVER NFR-2"
            print(f"{limit:>8}{scored:>8}{median:>12.1f}{worst:>11.1f}  {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
