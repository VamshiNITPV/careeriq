"""How commonly the market asks for each skill (`skills.demand_score`).

The column has been specified since Phase 5 — *"fraction of active jobs
requiring it"* — and was never filled. Phase 6.4's evaluation is what made it
matter: the skill dimension carries 25% of every match score and the ablation
found that **removing it raises NDCG@10 from 0.611 to 0.739**, i.e. it was
subtracting.

The measured reason is dilution. Jobs in this corpus list **18.5 skills on
average and up to 54**, and the most frequent ones are close to universal —
Python in 74.9% of postings, AWS 46.7%, Communication 45.0%, Problem Solving
38.1%. A requirement two out of five employers state tells you almost nothing
about whether one candidate fits better than another, yet it counted exactly as
much as a specialism named by one in fifty.

This is the classic inverse-document-frequency problem, and `demand_score` is
the term frequency it needs. `score_skill` turns it into a weight.

It also unblocks Phase 7: `skill_gaps.severity` is specified as
`demand_score * requirement weight` and cannot be computed while this is NULL.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Recompute every skill's share of the live market in one statement.
#:
#: **Only ACTIVE, unexpired postings count**, which is what makes this a measure
#: of current demand rather than of everything ever ingested. It follows that the
#: number drifts as the corpus turns over, and that is intended — a skill nobody
#: is hiring for any more should stop carrying weight.
#:
#: Skills no live job requires are set to 0 rather than left NULL, so "computed
#: and nobody wants it" is distinguishable from "never computed". The scorer
#: treats NULL as "fall back to flat weights" and 0 as a real answer, and
#: conflating them would silently disable the weighting on a partial run.
_RECOMPUTE = text("""
    WITH live AS (
        SELECT count(*) AS total
        FROM jobs
        WHERE status = 'ACTIVE' AND (expires_at IS NULL OR expires_at > now())
    ),
    wanted AS (
        SELECT js.skill_id, count(DISTINCT js.job_id) AS n
        FROM job_skills js
        JOIN jobs j ON j.id = js.job_id
        WHERE j.status = 'ACTIVE' AND (j.expires_at IS NULL OR j.expires_at > now())
        GROUP BY js.skill_id
    )
    UPDATE skills s
    SET demand_score = CASE
            WHEN (SELECT total FROM live) = 0 THEN NULL
            ELSE round(
                (coalesce(w.n, 0)::numeric / (SELECT total FROM live)), 4
            )
        END
    FROM (SELECT id FROM skills) AS all_skills
    LEFT JOIN wanted w ON w.skill_id = all_skills.id
    WHERE s.id = all_skills.id
""")

_COVERAGE = text("""
    SELECT count(*) FILTER (WHERE demand_score IS NOT NULL) AS scored,
           count(*) AS total,
           max(demand_score) AS highest
    FROM skills
""")


async def recompute_demand_scores(session: AsyncSession) -> tuple[int, int, float | None]:
    """Refresh every skill's demand score. Returns (scored, total, highest).

    One UPDATE rather than a row-per-skill loop: there are 267 skills today and
    no reason for 267 round trips. The repository rule applies — this does not
    commit, the caller owns the transaction.
    """
    await session.execute(_RECOMPUTE)
    row = (await session.execute(_COVERAGE)).one()
    return int(row[0]), int(row[1]), float(row[2]) if row[2] is not None else None
