"""Stage two of duplicate detection (ml.md section 5, US-3.2 AC2).

Stage one is a SHA-256 of the cleaned description — an index lookup that catches
a posting pasted twice. It is already in `JobService.submit`. This is the harder
half: **the same role reworded**, or posted by both an agency and the employer,
where no hash can match.

## Scoped, not exhaustive

Comparing every new posting against the whole corpus is O(n) per ingest and
unnecessary. The candidate set is narrowed to postings that share a company *or*
have a trigram-similar normalised title, which is what `ix_jobs_title_trgm`
exists for. A reworded re-post that changes neither the employer nor the gist of
the title is not a case worth the full scan.

## The threshold trades precision against recall, and neither target is met

Measured against a labelled set of 72 pairs in Phase 6.4
(`ml/evaluation/results/duplicates.md`). ml.md specifies cosine > 0.95 and
targets precision >= 0.95, recall >= 0.85. The sweep:

| Threshold | Precision | Recall | F1 |
|---|---|---|---|
| 0.95 (ml.md) | 0.750 | **1.000** | **0.857** |
| 0.97 (here) | **1.000** | 0.667 | 0.800 |

**Neither meets both targets, and on three true duplicates neither could be shown
to.** 0.95 actually has the better F1 and perfect recall; it is not shipped
because **the two errors cost differently**. A false positive sets
`status = 'DUPLICATE'`, which hides a real posting from everyone who would have
seen it. A false negative leaves a duplicate in a list that already contains it.
Precision is the side to protect when the action is destructive, so the threshold
sits above the one observed false positive — a same-employer pair at 0.960 where
a 15-year engineering *manager* role scored against a 5-year *engineer* role.

The cost of that choice is explicit: 0.97 is above a genuine duplicate at 0.951,
so one of the three known duplicates is missed.

**Why that false positive exists is the more useful finding.** Its score comes
almost entirely from several identical paragraphs of company marketing copy that
open both postings. `description_clean` is documented as boilerplate-stripped and
does not remove this kind; doing so would raise the signal available to duplicate
detection *and* to the semantic ranking dimension, which is a better lever than
any threshold and needs no larger labelled set to justify.

## Nothing is marked automatically

This module finds candidates; it does not set `status = 'DUPLICATE'`. Marking a
posting duplicate hides it from browse, so a detector at 50% precision would
conceal real jobs from users — and at the corpus size where precision could be
demonstrated, the decision can be revisited with evidence. The column and the
`canonical_job_id` pointer have been in place since Phase 5 for when it is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Cosine above which two postings are reported as near-duplicates.
#:
#: **Provisional.** ml.md says 0.95, which measured 0.750 precision and 1.000
#: recall; this value measured 1.000 and 0.667. It sits above the single observed
#: false positive (0.960) and above one of the three true duplicates (0.951),
#: which it therefore misses. Three positives cannot justify a threshold —
#: reclassifying one pair moves recall by a third. Revisit with a larger corpus.
DEFAULT_THRESHOLD = 0.97

#: Candidates returned per job. Generous: the caller is reviewing, not acting,
#: and a near-duplicate cluster at one employer can legitimately hold several.
DEFAULT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class NearDuplicate:
    job_id: uuid.UUID
    similarity: float
    #: Why this posting was a candidate at all — the same employer, a similar
    #: title, or both. Recorded because it is the first thing a reviewer asks,
    #: and because it says which half of the scoping earned its keep.
    shares_company: bool
    similar_title: bool


#: `%` is pg_trgm's similarity operator, which respects `pg_trgm.similarity_threshold`
#: (0.3 by default) and uses the GIN index on `normalized_title`.
#:
#: No vector is bound — the target is a CTE, the same arrangement `find_similar`
#: and `recall_jobs` use, so 768 floats never cross the wire.
#:
#: The model equality join is not optional: comparing vectors from two different
#: models is meaningless, and a near-duplicate decision made on mismatched
#: vectors would mark a real posting as a copy.
_NEAR = text("""
    WITH target AS (
        SELECT je.embedding, je.model_name, je.model_version,
               j.company_id, j.normalized_title
        FROM job_embeddings je
        JOIN jobs j ON j.id = je.job_id
        WHERE je.job_id = :job_id
        ORDER BY (je.model_name = :model_name) DESC, je.created_at DESC
        LIMIT 1
    )
    SELECT j.id,
           1 - (je.embedding <=> t.embedding) AS similarity,
           (t.company_id IS NOT NULL AND j.company_id = t.company_id) AS shares_company,
           (
             t.normalized_title IS NOT NULL
             AND j.normalized_title IS NOT NULL
             AND j.normalized_title % t.normalized_title
           ) AS similar_title
    FROM job_embeddings je
    CROSS JOIN target t
    JOIN jobs j ON j.id = je.job_id
    WHERE je.model_name = t.model_name
      AND je.model_version = t.model_version
      AND je.job_id <> :job_id
      AND j.status = 'ACTIVE'
      AND (
        (t.company_id IS NOT NULL AND j.company_id = t.company_id)
        OR (
          t.normalized_title IS NOT NULL
          AND j.normalized_title IS NOT NULL
          AND j.normalized_title % t.normalized_title
        )
      )
      AND 1 - (je.embedding <=> t.embedding) >= :threshold
    ORDER BY je.embedding <=> t.embedding
    LIMIT :limit
""")


async def find_near_duplicates(
    *,
    session: AsyncSession,
    job_id: uuid.UUID,
    model_name: str,
    threshold: float = DEFAULT_THRESHOLD,
    limit: int = DEFAULT_LIMIT,
) -> list[NearDuplicate]:
    """Postings that may be the same role as this one, closest first.

    An empty list means either "nothing similar enough" or "this job has no
    vector yet". The two are not distinguished here because no caller acts
    differently on them — unlike `/similar`, where the distinction is shown to a
    user and so has to be reported.
    """
    rows = (
        await session.execute(
            _NEAR,
            {
                "job_id": job_id,
                "model_name": model_name,
                "threshold": threshold,
                "limit": limit,
            },
        )
    ).all()

    return [
        NearDuplicate(
            job_id=row[0],
            similarity=float(row[1]),
            shares_company=bool(row[2]),
            similar_title=bool(row[3]),
        )
        for row in rows
    ]
