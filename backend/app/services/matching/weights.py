"""The ranking formula's configuration (ADR-005).

Separated from the scorers on purpose. ADR-005 says plainly that the weights
"are hand-tuned and *will* be wrong initially — they are configuration, validated
against the labelled evaluation set" — so they live where they can be read,
changed and versioned without touching arithmetic.

`RANKING_VERSION` is what makes that promise testable. When a learned ranker
eventually arrives it writes under a new version alongside these, and comparing
them is a query rather than a data migration.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from app.models.enums import SkillRequirement


class Dimension(StrEnum):
    """The six, in the order they are always presented.

    Declaration order is the presentation order, and that is deliberate: a fixed
    order is what makes two payloads diffable and what lets a user check the
    arithmetic by reading straight down a column (US-4.1 AC2).
    """

    SEMANTIC = "semantic"
    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LOCATION = "location"
    SALARY = "salary"


class DimensionStatus(StrEnum):
    """Why a dimension scored what it did.

    Four members rather than a boolean, because "we know nothing about you" and
    "the posting did not say" are different facts with different remedies.
    Collapsing them is exactly what produces a dishonest explanation — a button
    telling the user to fix their profile because an employer left a field blank.
    """

    #: Both sides had data and the formula ran.
    SCORED = "SCORED"
    #: The *job* stated no requirement, so ml.md's principled default applies
    #: (education → 1.0, salary → 0.5). Not ignorance about this person.
    NOT_STATED = "NOT_STATED"
    #: The *candidate* side is empty. Neutral, and the user can fix it.
    NEEDS_PROFILE = "NEEDS_PROFILE"
    #: Missing from the posting or from the index. Neutral, and never the
    #: user's fault — the interface must not offer them a remedy.
    NEEDS_DATA = "NEEDS_DATA"


#: The weight set. Must sum to exactly 1.
WEIGHTS: dict[Dimension, Decimal] = {
    Dimension.SEMANTIC: Decimal("0.35"),
    Dimension.SKILL: Decimal("0.25"),
    Dimension.EXPERIENCE: Decimal("0.15"),
    Dimension.EDUCATION: Decimal("0.10"),
    Dimension.LOCATION: Decimal("0.10"),
    Dimension.SALARY: Decimal("0.05"),
}

RANKING_VERSION = "v1-hand-tuned"

#: What a dimension scores when it could not be computed.
#:
#: Neutral, and the documented weight is **not** redistributed. Renormalising
#: onto the dimensions that did run is the obvious alternative and it is worse:
#: `weight` would become per-job, so the user could no longer reproduce the
#: score from a table they can look up (US-4.1 AC2 says "under the documented
#: weights"); and because 245 of 256 postings omit a salary, a job would have
#: its semantic weight silently inflated purely because its employer left a
#: field blank, which is ranking on something other than fit.
#:
#: The cost of keeping them fixed is real and worth stating. **Measured over 420
#: real candidate-job pairs, 2026-09-09:** `scored_weight` runs 0.35 to 1.00 with
#: a **median of 0.60**, and `overall_score` runs 21.8 to 91.0 (p05 33.8, median
#: 53.1, p95 72.2). So a typical score is built on roughly 60% evidence and 40%
#: neutral filler, and carries a corresponding offset toward the middle.
#:
#: Note the ceiling is 91, not the 80 that four pinned-at-neutral dimensions
#: would imply: profiles that have filled in preferences — and the education
#: fallback that reads `education_records` when the profile column is empty —
#: do let all six run. The floor is likewise 21.8 rather than 20.
#:
#: The answer to the compression is to disclose it — see `scored_weight` — not
#: to apply a second, undocumented transform to the output.
NEUTRAL = Decimal("0.5")

#: Cosine rescaling for the **candidate-to-job** case.
#:
#: **Measured, 2026-09-09**, over 960 candidate-job pairs from the live corpus:
#: min 0.218, p05 0.383, median 0.582, p95 0.698, max 0.751.
#:
#: ml.md §4.1 specifies `[0.3, 0.95]`, but that was measured on **job-to-job**
#: pairs, where near-duplicate postings reach 0.993. Resumes and job adverts are
#: different genres of document and have no such analogue, so the candidate-job
#: distribution is far more compressed. Rescaling from the job-to-job range
#: would make the best pair in the entire corpus score 0.69 and cap this
#: dimension permanently below 70.
#:
#: The floor sits just under the measured p05 rather than on it: anchoring on a
#: percentile means 5% of every user's results saturate at zero and lose all
#: ordering, and the bottom of the range is exactly where a career-switcher's
#: near-miss lives (US-4.3). The ceiling sits just above the observed maximum so
#: the best pair scores high without pinning the scale to one row.
#:
#: **Thin basis, stated honestly:** 8 candidates, all Indian tech roles. Phase
#: 6.4 re-derives both ends against the labelled evaluation set.
CANDIDATE_JOB_COSINE_FLOOR = Decimal("0.35")
CANDIDATE_JOB_COSINE_CEILING = Decimal("0.78")

#: Skill requirement weights (ml.md §4.1).
#:
#: ml.md also specifies `w(NICE_TO_HAVE) = 0.2`, which is **dead
#: configuration**: `SkillRequirement` has only REQUIRED and PREFERRED, in the
#: code and in the database. database.md §2 still describes a third member and
#: is stale. Nothing can ever select that weight, so it is not written here —
#: a constant no code path can reach reads as an oversight to whoever finds it.
SKILL_REQUIREMENT_WEIGHT: dict[SkillRequirement, Decimal] = {
    SkillRequirement.REQUIRED: Decimal("1.0"),
    SkillRequirement.PREFERRED: Decimal("0.5"),
}

#: Match quality for one skill (ml.md §4.1).
#:
#: `EXACT_INSUFFICIENT_YEARS` (0.7) is **currently unreachable**. It needs both a
#: job's `min_years` and the candidate's `years_of_experience`, and the latter is
#: populated on 0 of 207 candidate_skills rows — nothing writes it and no user
#: has typed it. Kept because the branch is correct and the data may arrive;
#: named here so its absence from the output is a known fact rather than a bug
#: someone hunts for. It is also why api.md's `partial[]` array is always empty.
SKILL_MATCH_EXACT = Decimal("1.0")
SKILL_MATCH_EXACT_INSUFFICIENT_YEARS = Decimal("0.7")
SKILL_MATCH_RELATED = Decimal("0.5")
SKILL_MATCH_ABSENT = Decimal("0.0")
