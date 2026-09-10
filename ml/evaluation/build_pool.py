"""Build the candidate pool for the matching dataset (ml.md section 4.3).

Run once to produce `ml/datasets/matching/queries.jsonl` and `pairs.jsonl`, the
latter with `label: null` for a human to fill in.

## Why pooling, rather than labelling the hybrid's top 20

If the pairs to be labelled are chosen by the system under evaluation, the
evaluation is rigged — every job the hybrid ranked highly gets a label, and
anything only a *baseline* would have surfaced is simply absent, so the baseline
cannot score for finding it. Precision@5 would then be measured over a set
curated by the thing being measured.

So the pool is the **union of the top K from every ranker**, plus a random
sample. That is standard TREC-style pooling and it is the cheapest thing that
makes the comparison in ml.md section 4.3 honest. The random draw matters
separately: without it the pool contains nothing any ranker disliked, and
precision has no way to be wrong.

## The sample-size problem, stated up front

This corpus holds **two distinct people** — one real resume and one test fixture
uploaded repeatedly. Eight candidate vectors exist and three distinct *texts*,
but two of those texts are the same person with slightly different extraction,
which is why the dedup below works on a normalised prefix rather than on
equality. Deduplicating on exact text counts that persona twice and inflates n
with no new information, which is the specific way a thin evaluation set
flatters itself.

So there are **two queries**, however many pairs get labelled. ml.md's per-query
metrics (Precision@5, NDCG@10, MRR) averaged over two queries are an anecdote,
not evidence, and the report must say so rather than print them as though n were
large. The pair-level correlation exists for exactly this reason.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import uuid
from decimal import Decimal
from typing import Any

from app.core.database import get_session_factory
from app.integrations.embeddings import get_embedding_provider
from app.models.embedding import JobEmbedding
from app.models.enums import JobSource, JobStatus
from app.models.job import Job
from app.repositories.matching import MatchingRepository
from app.services.matching.recall import recall_jobs
from app.services.matching.service import MatchingService
from app.services.matching.weights import Dimension
from sqlalchemy import func, select, text

from evaluation.baselines import rank_random, rank_tfidf

OUT = pathlib.Path("/ml/datasets/matching")

#: How many of each ranker's top results enter the pool.
#:
#: 15 rather than 10 so the pool reaches past Precision@10's horizon — a metric
#: whose pool stops at exactly 10 can never observe a ranker putting something
#: unlabelled at position 9.
TOP_K = 15

#: Random draws per query, so the pool is not composed entirely of things some
#: ranker liked. Without these, precision cannot be wrong.
RANDOM_DRAWS = 12

#: Jobs sampled from *outside* the recall set, so Recall@200 is a
#: measurement rather than a tautology. 276 jobs are eligible and recall
#: returns 200, so 76 are unreachable on any given request — these are
#: drawn from those.
OUT_OF_RECALL_DRAWS = 10

#: Characters of normalised resume text compared when deciding whether two
#: uploads describe the same person. The header — name, contact, first role — is
#: what identifies a candidate, and it is the part a parser is least likely to
#: mangle differently between two runs over the same file.
PERSONA_PREFIX = 400

#: Characters of the posting kept for the labeller to read. Enough to judge the
#: role; short enough that a hundred of them is a half-hour job and not a day's.
DESCRIPTION_CHARS = 700


#: Contact details, stripped before a resume is written to a committed file.
#:
#: **This repository is public.** `queries.jsonl` is committed so the evaluation
#: is reproducible, and the resume it contains belongs to a real person whose
#: phone number has no business being in a portfolio repo. Email addresses and
#: phone numbers contribute nothing to whether a job is a good match, so the
#: lexical baseline loses no signal by their absence — this costs nothing and
#: prevents publishing something that cannot be unpublished.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?\b\d{3,5}[\s-]?\d{3,5}[\s-]?\d{0,5}\b")


def redact(text: str) -> str:
    """Remove contact details from text that will be committed."""
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub("[phone]", text)


def _top(scores: dict[str, float], k: int) -> list[str]:
    return sorted(scores, key=lambda job_id: scores[job_id], reverse=True)[:k]


async def main() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    provider = get_embedding_provider()
    if provider is None:
        raise SystemExit("EMBEDDING_PROVIDER must be configured to build the pool")

    queries: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []

    labels_path = OUT / "labels.json"
    existing: dict[str, int] = (
        json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
    )
    if existing:
        print(f"re-applying {len(existing)} labels from {labels_path.name}")

    async with get_session_factory()() as session:
        repo = MatchingRepository(session)
        service = MatchingService(repo=repo, provider=provider)

        # One query per distinct *person*, not per indexed vector and not per
        # distinct text. See the module docstring: two of the three texts are the
        # same candidate, and SQL DISTINCT cannot see that.
        candidates = (
            await session.execute(
                text("""
                SELECT rv.id AS version_id, r.user_id, u.email, rv.raw_text
                FROM candidate_embeddings ce
                JOIN resume_versions rv ON rv.id = ce.resume_version_id
                JOIN resumes r ON r.id = rv.resume_id
                JOIN users u ON u.id = r.user_id
                WHERE rv.raw_text IS NOT NULL
                ORDER BY length(rv.raw_text) DESC
                """)
            )
        ).all()

        # Longest first, so when two uploads are the same person the fuller
        # extraction is the one kept.
        rows = []
        seen_personas: set[str] = set()
        for candidate in candidates:
            fingerprint = " ".join(candidate.raw_text.split()).lower()[:PERSONA_PREFIX]
            if fingerprint in seen_personas:
                print(f"  (skipped {candidate.email} — same person as a resume already taken)")
                continue
            seen_personas.add(fingerprint)
            rows.append(candidate)

        print(f"\n{len(rows)} distinct people, from {len(candidates)} indexed vectors\n")

        for index, row in enumerate(rows):
            version_id, user_id, email, raw_text = row
            query_id = f"q{index + 1}"
            queries.append(
                {
                    "query_id": query_id,
                    "resume_version_id": str(version_id),
                    "user_id": str(user_id),
                    # A label, not the account's email address. These files are
                    # committed to a public repository and the one real address
                    # here does not appear anywhere else in it — not even in the
                    # commit history, which uses a different one. "Which of the
                    # two resumes is this" is all the evaluation needs, and that
                    # is what this says.
                    "kind": "test-fixture" if email.endswith("example.com") else "real-resume",
                    "resume_chars": len(raw_text),
                    "resume_text": redact(raw_text),
                }
            )

            recalled = await recall_jobs(
                session=session,
                user_id=uuid.UUID(str(user_id)),
                resume_version_id=uuid.UUID(str(version_id)),
                model_name=provider.model_name,
                exclude_applied=False,
            )
            if not recalled:
                print(f"  {query_id}: no recall — skipped")
                continue

            ids = [r.job_id for r in recalled]
            by_id = {
                job.id: job
                for job in (
                    await session.scalars(
                        select(Job).where(
                            Job.id.in_(ids),
                            # Real postings only. The dev database also holds a
                            # handful of hand-made fixtures left by manual
                            # verification — "Open Ended Engineer", "Bounded
                            # Engineer" — carrying two skills and a sentence of
                            # description. Labelling those would measure the
                            # ranker against documents nobody wrote to be read,
                            # and they are disproportionately easy to rank
                            # because they contain almost nothing to get wrong.
                            Job.source == JobSource.PARTNER_API,
                        )
                    )
                ).all()
            }
            ordered = [by_id[i] for i in ids if i in by_id]
            cosines = {r.job_id: Decimal(str(r.similarity)) for r in recalled if r.job_id in by_id}

            scored = await service.match_many(
                user_id=uuid.UUID(str(user_id)),
                jobs=ordered,
                resume_version_id=uuid.UUID(str(version_id)),
                cosines=cosines,
            )

            hybrid = {str(r.job_id): float(r.overall_score) for r in scored}
            embedding = {str(job_id): float(c) for job_id, c in cosines.items()}
            skill = {
                str(r.job_id): float(
                    next(row.score for row in r.breakdown if row.dimension is Dimension.SKILL)
                )
                for r in scored
            }
            documents = {
                str(job.id): f"{job.title}\n{job.description_clean or job.description_raw}"
                for job in ordered
            }
            lexical = rank_tfidf(raw_text, documents)
            shuffled = rank_random(list(documents), seed=index)

            pooled: dict[str, list[str]] = {}
            for name, scores, k in (
                ("hybrid", hybrid, TOP_K),
                ("embedding", embedding, TOP_K),
                ("skill", skill, TOP_K),
                ("tfidf", lexical, TOP_K),
                ("random", shuffled, RANDOM_DRAWS),
            ):
                for job_id in _top(scores, k):
                    pooled.setdefault(job_id, []).append(name)

            print(
                f"  {query_id}: recalled {len(ordered)}, pooled {len(pooled)} "
                f"({email}, {len(raw_text)} chars)"
            )

            # Jobs the recall stage never returned.
            #
            # Without these, Recall@200 is **1.0 by construction** — the pool is
            # drawn from the recall set, so every labelled job is inside it by
            # definition and the metric can only ever agree with itself. ml.md
            # singles out Recall@200 as the measurement whose failure is
            # invisible in the ranking metrics, and a tautological 1.0 is exactly
            # that failure wearing a reassuring number.
            #
            # So a sample from outside is labelled too. If any of them turn out
            # to be relevant, stage one is losing good jobs and no amount of
            # reranking can recover them.
            missed = (
                await session.scalars(
                    select(Job)
                    .join(JobEmbedding, JobEmbedding.job_id == Job.id)
                    .where(
                        Job.source == JobSource.PARTNER_API,
                        Job.status == JobStatus.ACTIVE,
                        Job.id.notin_(ids),
                    )
                    # Deterministic, not `random()`. A committed dataset whose
                    # membership changes on every rebuild cannot be re-labelled
                    # or diffed, and the first rebuild after labelling silently
                    # discarded judgements for jobs the dice stopped drawing.
                    # Hashing the id with the query id gives a stable spread.
                    .order_by(func.md5(func.concat(Job.id, query_id)))
                    .limit(OUT_OF_RECALL_DRAWS)
                )
            ).all()
            for job in missed:
                by_id[job.id] = job
                pooled.setdefault(str(job.id), []).append("outside_recall")
            print(f"      + {len(missed)} sampled from outside the recall set")

            for job_id, sources in sorted(pooled.items()):
                job = by_id[uuid.UUID(job_id)]
                body = (job.description_clean or job.description_raw or "").strip()
                pairs.append(
                    {
                        "query_id": query_id,
                        "job_id": job_id,
                        "title": job.title,
                        "company": job.company.name if job.company is not None else None,
                        "location": job.location,
                        "min_years": str(job.min_years_experience)
                        if job.min_years_experience is not None
                        else None,
                        "skills": sorted(js.skill.name for js in job.skills),
                        "excerpt": " ".join(body.split())[:DESCRIPTION_CHARS],
                        # Recorded so a reader can tell whether a pair is here
                        # because a ranker liked it or because the dice did.
                        "pooled_by": sources,
                        # Carried over from labels.json when a pair has already
                        # been judged, so refreshing the pool after a corpus
                        # change does not throw away the labelling effort. Keyed
                        # on (query, job) rather than position, because the pool
                        # reorders whenever its contents change.
                        "label": existing.get(f"{query_id}|{job_id}"),
                    }
                )

    return queries, pairs


def _write(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    built_queries, built_pairs = asyncio.run(main())
    # Written after the loop closes: blocking file I/O inside an async
    # function is what ASYNC240 flags, and there is no reason to do it there.
    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "queries.jsonl", built_queries)
    _write(OUT / "pairs.jsonl", built_pairs)
    print(f"\nwrote {len(built_queries)} queries and {len(built_pairs)} pairs to {OUT}")
