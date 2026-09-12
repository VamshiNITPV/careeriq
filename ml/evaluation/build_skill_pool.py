"""Sample real postings for skill-extraction labelling (ml.md section 2.4).

    docker compose run --rm -v "$(pwd)/ml:/ml" backend \
        sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.build_skill_pool'

Writes `ml/datasets/skill_extraction/documents.jsonl`: one row per posting, with
the cleaned text a human has to read and the skills the shipped extractor found.
`gold` starts empty and is filled by a person — nothing here proposes an answer,
because a pool that arrives pre-labelled by the system under test is an exam it
wrote itself.

**Why job postings and not resumes**, when ml.md section 2.4 asks for 50 resumes.
There are three distinct resume texts in this corpus and 319 live postings, and
`services/job/skills.py` reuses `SkillMatcher` from the resume side — the same
taxonomy, the same alias resolution, the same longest-match scan. Postings
exercise the shared matcher on real, varied text; three resumes would not
exercise anything. What postings cannot test is the *resume* section
classifier's confidence weighting, which is separate and stays unmeasured. That
gap is stated in the report rather than papered over.

Sampling is deterministic (`md5(id)`), so re-running picks the same postings and
the labelled set stays stable. The same rule the matching pool follows, and for
the same reason: a dataset that moves when it is rebuilt cannot show a
regression.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

from app.core.database import get_session_factory
from app.models.job import Job
from app.repositories.skill import SkillRepository
from app.services.job.sections import detect_sections, section_map
from app.services.resume.skill_extraction import build_matcher
from sqlalchemy import func, select

OUT = pathlib.Path("/ml/datasets/skill_extraction")

#: How many postings to label.
#:
#: 30, not ml.md's 50. The number is bounded by what one person can read
#: carefully rather than by what sounds thorough — a larger set labelled quickly
#: is worse than a smaller one labelled properly, because sloppy gold labels make
#: every metric derived from them meaningless in a way no sample size fixes.
POOL_SIZE = 30

#: Text a labeller should not have to wade through to find the skills.
MAX_CHARS = 6000


async def main() -> None:
    async with get_session_factory()() as session:
        # Built from the database, exactly as `resume/pipeline.py` does. A
        # matcher assembled from the seed constants instead would be testing a
        # taxonomy the running system does not use.
        matcher = build_matcher(await SkillRepository(session).load_taxonomy())

        jobs = (
            await session.scalars(
                select(Job)
                .where(Job.status == "ACTIVE")
                .order_by(func.md5(func.concat(Job.id, 'skill-pool')))
                .limit(POOL_SIZE)
            )
        ).all()

        rows = []
        for job in jobs:
            text = job.description_clean or job.description_raw or ""
            sections = section_map(detect_sections(text))
            found = sorted({span.canonical_name for span in matcher.find_spans(text)})
            rows.append(
                {
                    "job_id": str(job.id),
                    "title": job.title,
                    "text": text[:MAX_CHARS],
                    "sections": sorted(s.value for s in sections),
                    # What the shipped extractor found. Recorded so the labeller
                    # can be compared against it afterwards — never shown as a
                    # suggestion, and never a starting point for `gold`.
                    "extracted": found,
                    # Filled by a human. `null` means "not yet labelled" and is
                    # distinct from `[]`, which is a real claim that the posting
                    # names no skills at all.
                    "gold": None,
                }
            )

    path = OUT / "documents.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} postings to {path}")
    print(f"unlabelled: {sum(1 for r in rows if r['gold'] is None)}")


if __name__ == "__main__":
    # Directory created outside the coroutine: ruff's ASYNC240 is right that a
    # blocking filesystem call inside an event loop is a latent stall, even when
    # this script is the only thing running.
    OUT.mkdir(parents=True, exist_ok=True)
    asyncio.run(main())
