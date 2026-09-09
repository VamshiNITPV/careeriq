"""Keep the corpus indexed, without anyone pressing a button.

**Scope.** One recurring task, not a task queue — the same scope note the job
fetch scheduler carries. ADR-008 and ADR-018 put real background work on Redis
in Phase 10, and this does not pre-empt that: no job types, no retries, no
dead-letter handling, no fan-out. It wakes up, asks the database what has no
current vector, and embeds a batch.

**Its own process.** This module is the entry point of the `embedder` container,
which is the only image that installs torch. Keeping the model out of the API's
image is the mitigation architecture.md's risk table names for cold starts, and
a lazy import alone would not achieve it — the dependency would still be
installed and still be pulled.

**The database is the queue.** There is nothing else to be one until Phase 10,
and the backlog queries in repositories/embedding.py are the whole of it.
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.logging import configure_logging, get_logger
from app.integrations.embeddings import get_embedding_provider
from app.services.embedding.indexer import DimensionMismatchError, run_once

log = get_logger(__name__)

#: How long before the first tick, when that is sooner than the interval.
#:
#: It does not index on startup. A crash loop would otherwise reload the model
#: on every restart, which is seconds of CPU and hundreds of megabytes each
#: time. Ten seconds is longer than any restart loop and short enough that a
#: developer who just started the container sees it work.
FIRST_TICK_SECONDS = 10


async def run_tick(settings: Settings) -> bool:
    """One pass. Returns whether anything was written.

    Every decision is read from the database rather than held between ticks, so
    a restart resumes exactly where it left off.
    """
    provider = get_embedding_provider()
    if provider is None:
        return False

    async with get_session_factory()() as session:
        jobs, candidates = await run_once(
            session=session, provider=provider, batch_size=settings.embedding_batch_size
        )
        await session.commit()

    if jobs.embedded or candidates.embedded or jobs.too_short or candidates.too_short:
        log.info(
            "embedded",
            model=provider.model_name,
            jobs_embedded=jobs.embedded,
            jobs_skipped=jobs.skipped,
            jobs_too_short=jobs.too_short,
            candidates_embedded=candidates.embedded,
            candidates_skipped=candidates.skipped,
            candidates_too_short=candidates.too_short,
        )
    return bool(jobs.embedded or candidates.embedded)


async def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    provider = get_embedding_provider()
    if provider is None:
        # Not an error. `none` is the default, and a container started without
        # a provider configured should say so once and stop, not restart-loop.
        log.warning("EMBEDDING_PROVIDER is 'none' — nothing to do")
        return

    log.info(
        "embedding worker started",
        model=provider.model_name,
        batch_size=settings.embedding_batch_size,
        interval_seconds=settings.embedding_interval_seconds,
    )

    delay = min(settings.embedding_interval_seconds, FIRST_TICK_SECONDS)
    while True:
        await asyncio.sleep(delay)
        try:
            wrote = await run_tick(settings)
        except DimensionMismatchError:
            # A configuration fault, not a transient one. Retrying it every
            # minute forever produces one identical ERROR per minute and fixes
            # nothing, so stop.
            log.exception("embedding worker stopping: model and column disagree")
            return
        except Exception:
            # Never let one bad tick kill the loop. The next one may well
            # succeed, and a worker that dies silently is worse than one that
            # logs and carries on.
            log.exception("embedding tick failed")
            wrote = False

        # Straight back round while there is a backlog, so the first run drains
        # the corpus in minutes rather than one batch per interval.
        delay = 0 if wrote else settings.embedding_interval_seconds


if __name__ == "__main__":
    asyncio.run(main())
