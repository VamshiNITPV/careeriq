"""Build the demo fixture from a real database (US-11, deployment).

Run once, against a development database that has jobs and embeddings, to
produce `demo_jobs.json` for `app/data/demo.py` to load.

    docker compose run --rm backend python -m app.data.export_demo

## It embeds the demo resume too, and must run where the model is

Run this in the **embedder** container, not the API one — the API image has no
torch, deliberately.

    docker compose run --rm -e EMBEDDING_PROVIDER=sentence_transformers \
        embedder python -m app.data.export_demo

The demo resume needs a vector of its own. Without one, stage-one recall returns
nothing at all and match-sorted browse is *empty* — not merely missing its
semantic dimension, which is what this file first assumed. Checked by seeding a
demo without it and finding `availability: PENDING` and zero jobs.

## Why the vectors are exported rather than generated on the server

The deployed VM has 1GB of RAM and the embedding model wants ~2GB, so the
embedder is not deployed at all. Without vectors the semantic dimension of every
match would report NEEDS_DATA and the demo would be missing the one thing the
project is actually about.

These are **real model output** for the text they accompany, not placeholders.
That matters: a fabricated vector would produce a similarity score that looks
meaningful and means nothing, which is the shape of problem ADR-012 exists to
refuse.

## What is exported

Postings, their skills, and their embeddings — no user data. Job rows are market
facts that arrived from a provider or a paste; nothing here is personal, and the
demo account is created fresh by the seed rather than copied from anyone.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.models.embedding import JobEmbedding
from app.models.job import Job
from app.models.skill import Skill

log = get_logger(__name__)

OUT = pathlib.Path(__file__).parent / "demo_jobs.json"
RESUME_OUT = pathlib.Path(__file__).parent / "demo_resume_vector.json"

#: Enough to fill a browse page and show a spread of match scores, few enough
#: that the file stays reviewable. 40 jobs of 768 floats is roughly 1MB.
HOW_MANY = 40


def _number(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


async def main() -> None:
    async with get_session_factory()() as session:
        rows = (
            await session.scalars(
                select(Job)
                .join(JobEmbedding, JobEmbedding.job_id == Job.id)
                .options(selectinload(Job.skills))
                .where(Job.description_raw.is_not(None))
                .order_by(Job.created_at.desc())
                .limit(HOW_MANY)
            )
        ).all()

        names = {
            row.id: row.name
            for row in (await session.scalars(select(Skill))).all()
        }

        vectors = {
            row.job_id: list(row.embedding)
            for row in (await session.scalars(select(JobEmbedding))).all()
        }

        payload = []
        for job in rows:
            vector = vectors.get(job.id)
            if vector is None:
                continue
            payload.append(
                {
                    "title": job.title,
                    "description_raw": job.description_raw,
                    "location": job.location,
                    "country_code": job.country_code,
                    "work_mode": job.work_mode.value if job.work_mode else None,
                    "employment_type": (
                        job.employment_type.value if job.employment_type else None
                    ),
                    "experience_level": (
                        job.experience_level.value if job.experience_level else None
                    ),
                    # Every numeric column here is NUMERIC, which SQLAlchemy
                    # hands back as Decimal and json refuses. Converted once at
                    # the boundary rather than with a custom encoder, so the
                    # file holds plain JSON that anything can read.
                    "min_years_experience": _number(job.min_years_experience),
                    "max_years_experience": _number(job.max_years_experience),
                    "salary_min": _number(job.salary_min),
                    "salary_max": _number(job.salary_max),
                    "salary_currency": job.salary_currency,
                    "salary_period": job.salary_period.value if job.salary_period else None,
                    # Names, not ids. The demo database seeds its own taxonomy,
                    # and an id from this database means nothing in that one.
                    "skills": [
                        {
                            "name": names[link.skill_id],
                            "requirement": link.requirement.value,
                        }
                        for link in job.skills
                        if link.skill_id in names
                    ],
                    "embedding": vector,
                }
            )

    OUT.write_text(json.dumps(payload), encoding="utf-8")

    # The demo resume, embedded by the same model as the jobs. Comparing
    # vectors from two different models is meaningless, so this is not
    # optional garnish — it is what makes the match scores comparable.
    from app.data.demo import RESUME_TEXT
    from app.integrations.embeddings import get_embedding_provider

    provider = get_embedding_provider()
    if provider is None:
        raise RuntimeError(
            "EMBEDDING_PROVIDER is not set to a real provider. Run this in the "
            "embedder container: the API image has no model, by design."
        )
    vector = (await provider.embed([RESUME_TEXT]))[0]
    RESUME_OUT.write_text(json.dumps(list(vector)), encoding="utf-8")
    # structlog, not print: it writes to stdout like print would, and the rest
    # of the codebase is logged rather than printed.
    log.info(
        "demo fixture written",
        jobs=len(payload),
        kilobytes=OUT.stat().st_size // 1024,
        resume_dimensions=len(vector),
    )


if __name__ == "__main__":
    asyncio.run(main())
