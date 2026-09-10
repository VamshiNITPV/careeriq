"""Build the duplicate-detection dataset (ml.md section 5).

    docker compose run --rm -v "$(pwd -W)/ml:/ml" backend \
        sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.build_duplicate_pool'

Writes `ml/datasets/duplicates/pairs.jsonl` with `label: null` for a human, and
re-applies anything already in `labels.json`.

## Why the pool goes well below the decision threshold

The detector's threshold is 0.97. Pooling only pairs above it would make recall
unmeasurable: a true duplicate sitting at 0.94 would never be labelled, so the
detector could not be caught missing it, and recall would be 1.0 by construction
— the same trap the matching dataset fell into with Recall@200.

So the pool starts at **0.88**, comfortably under any plausible threshold. That
makes the false-negative region visible and is what lets the precision/recall
curve in the report mean anything.

## Scoped the way the detector is scoped

Pairs are restricted to the same company or a trigram-similar title, because that
is the candidate set the detector actually considers. Labelling pairs outside it
would measure a detector nobody is proposing to build — the scoping is part of
the design, not an optimisation applied afterwards.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any

from app.core.database import get_session_factory
from sqlalchemy import text

OUT = pathlib.Path("/ml/datasets/duplicates")

#: Lower bound of the pool. Well under the 0.97 decision threshold so the
#: false-negative region is labelled rather than assumed empty.
FLOOR = 0.88

#: Characters of each description kept for the labeller. Two postings have to be
#: read side by side to judge whether they are the same role, so this is larger
#: than the matching dataset's excerpt.
EXCERPT = 600

_PAIRS = text("""
    SELECT 1 - (a.embedding <=> b.embedding)      AS similarity,
           ja.id AS a_id, ja.title AS a_title, ca.name AS a_company,
           ja.location AS a_location, ja.min_years_experience AS a_years,
           left(regexp_replace(coalesce(ja.description_clean, ja.description_raw),
                '\\s+', ' ', 'g'), :excerpt) AS a_excerpt,
           jb.id AS b_id, jb.title AS b_title, cb.name AS b_company,
           jb.location AS b_location, jb.min_years_experience AS b_years,
           left(regexp_replace(coalesce(jb.description_clean, jb.description_raw),
                '\\s+', ' ', 'g'), :excerpt) AS b_excerpt,
           (ja.company_id IS NOT NULL AND ja.company_id = jb.company_id) AS shares_company,
           (ja.normalized_title IS NOT NULL AND jb.normalized_title IS NOT NULL
            AND ja.normalized_title % jb.normalized_title)                AS similar_title,
           (ja.content_hash = jb.content_hash)                            AS same_hash,
           -- Whether both postings open with the same 300 characters. Company
           -- marketing copy runs to several paragraphs and `description_clean`
           -- does not strip it, so two unrelated roles at one employer can score
           -- highly on text describing neither. Flagged per pair rather than
           -- inferred from a couple of examples, so the report can count it.
           (left(regexp_replace(coalesce(ja.description_clean, ''), '\\s+', ' ', 'g'), 300)
            = left(regexp_replace(coalesce(jb.description_clean, ''), '\\s+', ' ', 'g'), 300))
                                                                          AS shared_opening
    FROM job_embeddings a
    JOIN job_embeddings b
      ON a.job_id < b.job_id
     AND a.model_name = b.model_name
     AND a.model_version = b.model_version
    JOIN jobs ja ON ja.id = a.job_id AND ja.source = 'PARTNER_API'
    JOIN jobs jb ON jb.id = b.job_id AND jb.source = 'PARTNER_API'
    LEFT JOIN companies ca ON ca.id = ja.company_id
    LEFT JOIN companies cb ON cb.id = jb.company_id
    WHERE 1 - (a.embedding <=> b.embedding) >= :floor
      AND (
        (ja.company_id IS NOT NULL AND ja.company_id = jb.company_id)
        OR (ja.normalized_title IS NOT NULL AND jb.normalized_title IS NOT NULL
            AND ja.normalized_title % jb.normalized_title)
      )
    ORDER BY similarity DESC
""")


async def main() -> list[dict[str, Any]]:
    labels_path = OUT / "labels.json"
    existing: dict[str, int] = (
        json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
    )
    if existing:
        print(f"re-applying {len(existing)} labels")

    async with get_session_factory()() as session:
        rows = (await session.execute(_PAIRS, {"floor": FLOOR, "excerpt": EXCERPT})).all()

    pairs: list[dict[str, Any]] = []
    for row in rows:
        key = f"{row.a_id}|{row.b_id}"
        pairs.append(
            {
                "pair_id": key,
                "similarity": round(float(row.similarity), 4),
                "shares_company": bool(row.shares_company),
                "similar_title": bool(row.similar_title),
                # Stage one already catches these. Recorded so the report can say
                # how much work stage two is actually left to do.
                "same_content_hash": bool(row.same_hash),
                # Both descriptions begin with the same 300 characters — almost
                # always the employer's marketing blurb rather than the role.
                "shared_opening": bool(row.shared_opening),
                "a": {
                    "id": str(row.a_id),
                    "title": row.a_title,
                    "company": row.a_company,
                    "location": row.a_location,
                    "min_years": str(row.a_years) if row.a_years is not None else None,
                    "excerpt": row.a_excerpt,
                },
                "b": {
                    "id": str(row.b_id),
                    "title": row.b_title,
                    "company": row.b_company,
                    "location": row.b_location,
                    "min_years": str(row.b_years) if row.b_years is not None else None,
                    "excerpt": row.b_excerpt,
                },
                #: 1 = the same role posted twice, 0 = two genuinely different
                #: openings. Binary, unlike the matching labels: "somewhat the
                #: same job" is not a thing, and a graded scale here would invite
                #: the labeller to dodge the decision the detector has to make.
                "label": existing.get(key),
            }
        )

    return pairs


def _write(pairs: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "pairs.jsonl").open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")
    unlabelled = sum(1 for pair in pairs if pair["label"] is None)
    print(f"wrote {len(pairs)} pairs to {OUT} ({unlabelled} unlabelled)")


if __name__ == "__main__":
    _write(asyncio.run(main()))
