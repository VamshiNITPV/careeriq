"""The six dimensions of the ranking formula (ml.md section 4.1).

Every function here is **pure** — plain values in, a `DimensionScore` out. No
session, no ORM instance, no I/O. The service layer does the loading and the
weighting; this module does the arithmetic and writes the sentence explaining
it. That split is what makes the boundary cases testable one at a time, and the
boundary cases are where a scoring formula actually goes wrong.

## The rules the reason strings follow

These are not style preferences. ADR-012 forbids inventing anything about a
candidate or a posting, and a reason string is the one place in the system where
a fabricated sentence would look completely authoritative.

**R1 — never state a fact about the user we do not hold.** api.md's worked
example writes *"You have 3.5 years; the role asks for 3-6"*. That sentence may
only be produced on a branch where `candidate_years is not None`. It is enforced
structurally: the unknown branches return from `_unknown()`, which takes no
candidate value and therefore cannot interpolate one, and a property test
asserts that no reason on an unknown-status row contains a digit.

**R2 — say what we did instead.** "...so this counts as neutral" rather than a
bare "not recorded", otherwise a 5.0 contribution appears in the breakdown from
nowhere and the arithmetic looks broken.

**R3 — name a remedy only where one exists.** The copy points at controls the
user can actually reach on `/profile`. `years_of_experience` and
`highest_education` have no editor at all, so those reasons point at the work
history and education sections, which `<CareerProfile />` does edit.

**R4 — the semantic reason must not claim to know *what* matched.** api.md's
example says "Your API and distributed-systems experience closely matches...".
We have one cosine between two 768-dimension vectors and no attribution
mechanism whatsoever. The phrasing is banded on the rescaled score and describes
the strength of the resemblance, never its substance. And the number itself is
never printed — the rule `SimilarJobs` already follows.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.enums import EducationLevel, SalaryPeriod, SkillRequirement, WorkMode
from app.services.matching.weights import (
    CANDIDATE_JOB_COSINE_CEILING,
    CANDIDATE_JOB_COSINE_FLOOR,
    NEUTRAL,
    SKILL_MATCH_ABSENT,
    SKILL_MATCH_EXACT,
    SKILL_MATCH_RELATED,
    SKILL_REQUIREMENT_WEIGHT,
    DimensionStatus,
)

#: Dimension scores are quantised so the same inputs always produce the same
#: bytes. Four places is far finer than anything displayed and coarse enough
#: that Decimal division cannot leave a 28-digit tail in the payload.
_Q = Decimal("0.0001")

ONE = Decimal("1")
ZERO = Decimal("0")

#: Lower bound on `demand_score` when converting it to a rarity weight.
#:
#: Guards a division by zero, and caps how much a single obscure requirement can
#: dominate a posting: at 1% the weight is log(100) ≈ 4.6, about sixteen times a
#: skill half the market names. Below that the curve grows without limit and one
#: rare tag would decide the dimension on its own.
_RARITY_FLOOR = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class DimensionScore:
    """One dimension's result: a number in [0, 1], why it is that, and a sentence."""

    score: Decimal
    status: DimensionStatus
    reason: str


def _scored(score: Decimal, reason: str) -> DimensionScore:
    return DimensionScore(score=score.quantize(_Q), status=DimensionStatus.SCORED, reason=reason)


def _unknown(status: DimensionStatus, reason: str) -> DimensionScore:
    """A dimension that could not be computed.

    Always `NEUTRAL`, and — this is the point of the helper — it accepts no
    candidate or job value, so no branch reaching it can interpolate a fact we
    do not hold. R1 is enforced by what this signature cannot receive.
    """
    if status is DimensionStatus.SCORED:  # pragma: no cover - programming error
        raise ValueError("_unknown() cannot produce a SCORED row")
    return DimensionScore(score=NEUTRAL, status=status, reason=reason)


def _stated(score: Decimal, reason: str) -> DimensionScore:
    """The job stated no requirement, so ml.md's principled default applies.

    Distinct from `_unknown` because the score is not neutral — education and
    experience award 1.0 here, on the rule that the absence of a requirement is
    not a penalty. The row still carries `NOT_STATED` rather than `SCORED`: the
    points are real, but they are not evidence about this person, so they must
    not count toward `scored_weight`.
    """
    return DimensionScore(
        score=score.quantize(_Q), status=DimensionStatus.NOT_STATED, reason=reason
    )


# --------------------------------------------------------------------- semantic


def _semantic_band(rescaled: Decimal) -> str:
    """Banded phrasing for the rescaled cosine (R4).

    Describes how strong the resemblance is and never what it consists of.
    """
    if rescaled >= Decimal("0.75"):
        return "reads as closely related work"
    if rescaled >= Decimal("0.5"):
        return "clearly overlaps with this posting"
    if rescaled >= Decimal("0.25"):
        return "partly overlaps with this posting"
    return "has little overlap with this posting"


def score_semantic(cosine: Decimal | None) -> DimensionScore:
    """Cosine between the candidate's and the job's document vectors, rescaled.

    `cosine` is `None` when either side has no vector, or when embeddings are
    switched off entirely. That is `NEEDS_DATA` and never `NEEDS_PROFILE`: a
    user who has uploaded a resume the indexer has not reached yet has done
    nothing wrong, and must not be shown a call to action suggesting otherwise.

    The rescale range is the **candidate-to-job** one, which is materially
    narrower than the job-to-job range ml.md quotes — see `weights.py`. Clamping
    is load-bearing at both ends: the measured minimum is 0.218, well under the
    floor.
    """
    if cosine is None:
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "We haven't compared this posting against your resume yet, so this counts as neutral.",
        )

    span = CANDIDATE_JOB_COSINE_CEILING - CANDIDATE_JOB_COSINE_FLOOR
    rescaled = (cosine - CANDIDATE_JOB_COSINE_FLOOR) / span
    rescaled = min(ONE, max(ZERO, rescaled))
    return _scored(rescaled, f"Your resume {_semantic_band(rescaled)}.")


# ------------------------------------------------------------------------ skill


@dataclass(frozen=True, slots=True)
class SkillRequirementInput:
    """One row of `job_skills`, reduced to what the formula reads."""

    skill_id: uuid.UUID
    name: str
    requirement: SkillRequirement


@dataclass(frozen=True, slots=True)
class SkillBuckets:
    """Every skill the job asks for, sorted into the three the explanation shows.

    Produced once and used twice — for the score and for the `matched` /
    `partial` / `missing` id arrays. One classification pass rather than two
    means the arrays cannot drift out of agreement with the number above them,
    which is the failure that makes an explanation untrustworthy.
    """

    matched: tuple[SkillRequirementInput, ...]
    partial: tuple[SkillRequirementInput, ...]
    missing: tuple[SkillRequirementInput, ...]


def classify_skills(
    *,
    requirements: Sequence[SkillRequirementInput],
    candidate_skill_ids: Iterable[uuid.UUID],
    parent_of: Mapping[uuid.UUID, uuid.UUID | None],
) -> SkillBuckets:
    """Sort a job's requirements against what the candidate holds.

    `parent_of` maps a skill id to its immediate parent in the taxonomy, for
    both the job's skills and the candidate's. **One level only, in both
    directions.** The tree is genuinely multi-level — `BCDU-Net -> U-Net -> ...
    -> Machine Learning` — so crediting any ancestor would score someone who
    listed one segmentation architecture as knowing Machine Learning outright.
    One level is the "React implies JavaScript" relationship the rule was
    written for; two is a claim about the candidate we cannot support.

    `partial` here means a taxonomy match. ml.md's *other* partial — an exact
    match with insufficient years, worth 0.7 — is **unreachable today**: it
    needs `candidate_skills.years_of_experience`, which is populated on 0 of 207
    rows because nothing writes it and no user has typed it. So api.md's example
    reason for a partial ("Job asks for 3+ years; you have 1") is a sentence
    this code cannot currently produce, and every exact match scores 1.0.
    """
    held = set(candidate_skill_ids)
    # Precomputed so the related-match test below is a set lookup rather than a
    # scan over the candidate's skills for every requirement.
    held_parents = {parent for sid in held if (parent := parent_of.get(sid)) is not None}

    matched: list[SkillRequirementInput] = []
    partial: list[SkillRequirementInput] = []
    missing: list[SkillRequirementInput] = []

    for req in requirements:
        if req.skill_id in held:
            matched.append(req)
        elif parent_of.get(req.skill_id) in held or req.skill_id in held_parents:
            # Either the candidate holds this skill's parent (job wants React,
            # they know JavaScript) or they hold one of its children (job wants
            # JavaScript, they know React).
            partial.append(req)
        else:
            missing.append(req)

    return SkillBuckets(matched=tuple(matched), partial=tuple(partial), missing=tuple(missing))


def skill_rarity(demand: Decimal | None) -> Decimal:
    """How much a requirement discriminates, from its share of the live market.

    `demand` is `skills.demand_score` — the fraction of active postings asking
    for it. The weight is the textbook inverse document frequency, `log(1 /
    demand)`, so a skill every employer names tends to zero and a specialism
    carries several times the weight of a commonplace.

    **This exists because the flat version measurably hurt.** Phase 6.4's
    ablation found that removing the skill dimension entirely raised NDCG@10
    from 0.611 to 0.739. The cause was dilution: jobs list 18.5 skills on
    average and up to 54, and the commonest are near-universal (Python 74.9%,
    AWS 46.7%, Communication 45.0%). Counting "Communication" as heavily as a
    specialism drags every candidate toward the same score.

    `None` means the score has never been computed — a fresh database, or a
    fixture that never ran `recompute_demand_scores`. That returns 1, which
    reproduces the old flat behaviour exactly, so this cannot break an
    environment that has not run the recompute.

    The floor is not decorative: `demand` of 0 would divide by zero, and a skill
    at 0.001 would otherwise dominate every other requirement in the posting on
    the strength of being rare rather than being important.
    """
    if demand is None:
        return ONE
    floored = max(demand, _RARITY_FLOOR)
    return Decimal(str(math.log(1 / float(floored))))


def score_skill(
    *,
    buckets: SkillBuckets,
    has_candidate_skills: bool,
    demand: Mapping[uuid.UUID, Decimal | None] | None = None,
) -> DimensionScore:
    """Weighted coverage of the skills this job asks for.

        skill = Σ w(r)·idf(s)·m(s) / Σ w(r)·idf(s)

    `idf(s)` weights each requirement by how rare it is in the live market — see
    `skill_rarity`. Passing no `demand` map, or one whose values are all None,
    collapses this to the original `Σ w(r)·m(s) / Σ w(r)`.

    `has_candidate_skills` is passed rather than inferred from the buckets,
    because an empty profile and a profile that simply matches nothing produce
    the same three buckets and are not the same fact. One earns a call to
    action; the other is a real score of zero, and showing a CTA for it would be
    telling the user to fix something that is not broken.
    """
    everything = buckets.matched + buckets.partial + buckets.missing
    if not everything:
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "This posting doesn't list the skills it needs, so this counts as neutral.",
        )

    if not has_candidate_skills:
        return _unknown(
            DimensionStatus.NEEDS_PROFILE,
            "We don't have any skills on your profile yet, so this counts as neutral. "
            "Upload a resume or add them by hand.",
        )

    rarity = demand or {}
    total_weight = ZERO
    earned = ZERO
    for match_value, bucket in (
        (SKILL_MATCH_EXACT, buckets.matched),
        (SKILL_MATCH_RELATED, buckets.partial),
        (SKILL_MATCH_ABSENT, buckets.missing),
    ):
        for req in bucket:
            weight = SKILL_REQUIREMENT_WEIGHT[req.requirement] * skill_rarity(
                rarity.get(req.skill_id)
            )
            total_weight += weight
            earned += weight * match_value

    if total_weight == ZERO:
        # Every requirement weighed nothing, which happens only when a posting
        # asks solely for skills the whole market asks for. There is no ratio to
        # take, and the honest answer is that these requirements cannot separate
        # one candidate from another — not that the candidate scored zero.
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "The skills this role lists are ones nearly every posting asks for, "
            "so they can't tell candidates apart. This counts as neutral.",
        )

    reason = _reason_skill(
        len(everything),
        [r.name for r in buckets.matched],
        [r.name for r in buckets.partial],
    )
    return _scored(earned / total_weight, reason)


def _reason_skill(asked: int, exact: list[str], related: list[str]) -> str:
    """Name the skills rather than only counting them.

    A bare "4 of 9" tells the reader the score is low without telling them
    anything they can act on. Every name here comes from the posting's own
    requirement rows, so nothing is invented.
    """
    if not exact and not related:
        if asked == 1:
            return "The one skill this role asks for isn't on your profile."
        return f"None of the {asked} skills this role asks for are on your profile."

    parts = []
    if exact:
        parts.append(f"you have {_and_list(exact)}")
    if related:
        parts.append(f"you have closely related experience for {_and_list(related)}")
    joined = ", and ".join(parts)
    if asked == 1:
        return f"Of the one skill this role asks for, {joined}."
    return f"Of the {asked} skills this role asks for, {joined}."


def _and_list(names: list[str], limit: int = 4) -> str:
    """`a, b and c`, truncated — a reason string is one line, not an inventory."""
    if len(names) > limit:
        return f"{', '.join(names[:limit])} and {len(names) - limit} more"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


# ------------------------------------------------------------------- experience


#: How much one year beyond the stated maximum costs, and the floor it stops at
#: (ml.md section 4.1). Asymmetric on purpose: being under-experienced is a real
#: barrier, being over-experienced is a mild signal. A symmetric penalty would
#: bury senior candidates on roles they would walk into.
_OVER_PENALTY_PER_YEAR = Decimal("0.05")
_OVER_FLOOR = Decimal("0.7")


def years_from_history(
    entries: Sequence[tuple[date | None, date | None, bool]], *, today: date
) -> Decimal | None:
    """Total years of work from `(start_date, end_date, is_current)` rows.

    A fallback for the common case that `Profile.years_of_experience` is unset —
    which is every profile today, because `services/profile.py` deliberately
    excludes it from autofill (inferring years from free text needs reference
    data this project does not have).

    Summing spans rather than taking `max(end) - min(start)` because a gap
    between roles is not experience. Overlapping roles are **not** merged, which
    can overcount someone who held two jobs at once; the alternative is an
    interval union whose result would still be a guess, and this errs toward
    crediting the candidate rather than against them.
    """
    months = 0
    for start, end, is_current in entries:
        if start is None:
            continue
        finish = today if is_current or end is None else end
        if finish < start:
            continue
        months += (finish.year - start.year) * 12 + (finish.month - start.month)

    if months == 0:
        return None
    return (Decimal(months) / Decimal(12)).quantize(Decimal("0.1"))


def score_experience(
    *,
    candidate_years: Decimal | None,
    min_years: Decimal | None,
    max_years: Decimal | None,
) -> DimensionScore:
    """The asymmetric curve from ml.md section 4.1.

        in range   -> 1.0
        below min  -> max(0, 1 - (min - actual) / min)
        above max  -> max(0.7, 1 - 0.05 * (actual - max))
    """
    if min_years is None and max_years is None:
        return _stated(ONE, "This role doesn't state an experience requirement.")

    if candidate_years is None:
        return _unknown(
            DimensionStatus.NEEDS_PROFILE,
            "We don't know how long you've been working, so this counts as neutral. "
            "Add your work history to your profile.",
        )

    asked = _asked_for(min_years, max_years)

    if min_years is not None and candidate_years < min_years:
        # min_years is zero-guarded: you cannot be below zero years, so the
        # branch is unreachable at min == 0, but a division by it would not be.
        shortfall = (min_years - candidate_years) / min_years if min_years > 0 else ZERO
        score = max(ZERO, ONE - shortfall)
        return _scored(
            score, f"You have {_years(candidate_years)}, and this role asks for {asked}."
        )

    if max_years is not None and candidate_years > max_years:
        over = candidate_years - max_years
        score = max(_OVER_FLOOR, ONE - _OVER_PENALTY_PER_YEAR * over)
        return _scored(
            score,
            f"You have {_years(candidate_years)}, comfortably past the "
            f"{_years(max_years)} this role tops out at.",
        )

    return _scored(ONE, f"You have {_years(candidate_years)}, and this role asks for {asked}.")


def _asked_for(min_years: Decimal | None, max_years: Decimal | None) -> str:
    """What the posting stated, in the posting's own terms.

    Both ends when it gave both, so the reason reads "asks for 3-6 years" rather
    than silently dropping the ceiling and leaving the reader to wonder why 8
    years scored below 5.
    """
    if min_years is not None and max_years is not None:
        return f"{_number(min_years)}-{_years(max_years)}"
    if min_years is not None:
        return f"at least {_years(min_years)}"
    return f"up to {_years(max_years)}"  # type: ignore[arg-type]


def _number(value: Decimal) -> str:
    """`3`, `3.5` — never `3.0`."""
    if value == value.to_integral_value():
        return f"{value.to_integral_value()}"
    return f"{value.normalize()}"


def _years(value: Decimal) -> str:
    """`3 years`, `1 year`, `3.5 years` — never `3.0 years`."""
    return f"{_number(value)} year" if value == ONE else f"{_number(value)} years"


# -------------------------------------------------------------------- education

_ONE_LEVEL_BELOW = Decimal("0.6")
_TWO_OR_MORE_BELOW = Decimal("0.2")


def score_education(
    *, candidate_level: EducationLevel | None, required_level: EducationLevel | None
) -> DimensionScore:
    """Ordinal comparison on `EducationLevel.rank`.

    `rank` is defined on the enum with an explicit mapping precisely so that
    reordering the members cannot silently change ranking behaviour — reused
    here rather than duplicated.
    """
    if required_level is None:
        return _stated(ONE, "This role doesn't state an education requirement.")

    if candidate_level is None:
        return _unknown(
            DimensionStatus.NEEDS_PROFILE,
            "We don't have your education on file, so this counts as neutral. "
            "Add it to your profile.",
        )

    gap = candidate_level.rank - required_level.rank
    if gap >= 0:
        # Phrased with the requirement first because the labels carry their own
        # article — "you meet the a bachelor's degree" is what the obvious
        # wording produces.
        return _scored(ONE, f"This role asks for {_education(required_level)}, and you meet it.")
    if gap == -1:
        return _scored(
            _ONE_LEVEL_BELOW,
            f"This role asks for {_education(required_level)}, one level above yours.",
        )
    return _scored(
        _TWO_OR_MORE_BELOW,
        f"This role asks for {_education(required_level)}, which is well above yours.",
    )


_EDUCATION_LABEL = {
    EducationLevel.NONE: "no formal qualification",
    EducationLevel.HIGH_SCHOOL: "a high-school qualification",
    EducationLevel.DIPLOMA: "a diploma",
    EducationLevel.BACHELORS: "a bachelor's degree",
    EducationLevel.MASTERS: "a master's degree",
    EducationLevel.DOCTORATE: "a doctorate",
}


def _education(level: EducationLevel) -> str:
    return _EDUCATION_LABEL[level]


# --------------------------------------------------------------------- location

_SAME_COUNTRY_RELOCATING = Decimal("0.7")
_SAME_COUNTRY_STAYING = Decimal("0.3")
_DIFFERENT_COUNTRY = Decimal("0.1")

#: Job locations arrive half-clean from the upstream feed: `Bengaluru,
#: Karnataka, IN` sits beside a bare `IN`, `Bengaluru, India`, and
#: `India | Type: Full-Time`. Split on every separator any of those use.
_LOCATION_SEPARATORS = re.compile(r"[,/|;]|\s+-\s+")

#: Work modes that turn up inside a locations list. One real profile has the
#: string "Remote" in `preferred_locations`, which is a work mode in a places
#: array — matching it against a city name would be nonsense, so it is lifted
#: out and read as the preference it plainly is.
_WORK_MODE_WORDS = {"remote", "hybrid", "onsite", "on-site", "work from home", "wfh"}


def _place_tokens(*values: str | None) -> frozenset[str]:
    """Normalised place names from free-text location strings.

    Drops `key: value` fragments (`Type: Full-Time` rides along in the feed's
    location field) and work-mode words, which are handled separately.
    """
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        for part in _LOCATION_SEPARATORS.split(value):
            token = part.strip().lower()
            if not token or ":" in token or token in _WORK_MODE_WORDS:
                continue
            tokens.add(token)
    return frozenset(tokens)


def score_location(
    *,
    job_location: str | None,
    job_country: str | None,
    job_work_mode: WorkMode | None,
    candidate_location: str | None,
    candidate_country: str | None,
    preferred_locations: Sequence[str],
    preferred_work_modes: Sequence[WorkMode],
    open_to_relocation: bool,
) -> DimensionScore:
    """The four branches from ml.md section 4.1.

    All four are implemented, and on today's corpus only one of them can fire:
    `jobs.country_code` holds a single distinct value. That is a fact about the
    data rather than about the code, and writing three unreachable branches now
    is cheaper than discovering they were never written on the day the corpus
    gains a second country.
    """
    wants_remote = WorkMode.REMOTE in preferred_work_modes or any(
        (loc or "").strip().lower() in _WORK_MODE_WORDS for loc in preferred_locations
    )
    candidate_places = _place_tokens(candidate_location, *preferred_locations)

    if not candidate_places and not wants_remote and candidate_country is None:
        return _unknown(
            DimensionStatus.NEEDS_PROFILE,
            "We don't know where you want to work, so this counts as neutral. "
            "Add your preferred locations to your profile.",
        )

    if job_work_mode is WorkMode.REMOTE and wants_remote:
        return _scored(ONE, "This role is remote, which is what you're looking for.")

    if job_location is None and job_country is None:
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "This posting doesn't say where the role is based, so this counts as neutral.",
        )

    job_places = _place_tokens(job_location)
    if candidate_places & job_places:
        return _scored(ONE, "This role is in a place you said you'd work.")

    if job_country is not None and candidate_country is not None:
        if job_country.upper() == candidate_country.upper():
            if open_to_relocation:
                return _scored(
                    _SAME_COUNTRY_RELOCATING,
                    "This role is in your country but not a place you listed, "
                    "and you're open to relocating.",
                )
            return _scored(
                _SAME_COUNTRY_STAYING,
                "This role is in your country but not a place you listed, "
                "and you haven't said you'd relocate.",
            )
        return _scored(_DIFFERENT_COUNTRY, "This role is in a different country.")

    # One side has a country and the other does not, so nothing can be compared
    # beyond the place names that already failed to match.
    return _unknown(
        DimensionStatus.NEEDS_DATA,
        "We can't tell how this role's location compares with yours, "
        "so this counts as neutral.",
    )


# ----------------------------------------------------------------------- salary

#: Hours in a working year, for normalising an hourly rate. 40 x 52.
_HOURS_PER_YEAR = Decimal("2080")
_MONTHS_PER_YEAR = Decimal("12")


def _to_yearly(amount: Decimal, period: SalaryPeriod | None) -> Decimal | None:
    """Convert a quoted figure to a yearly one, or `None` if we cannot.

    A missing period is not assumed to be yearly. Reading a monthly Indian
    salary as an annual one understates it twelvefold, and a confidently wrong
    number here would drag the whole score down for a reason the user could
    never diagnose.
    """
    if period is None:
        return None
    if period is SalaryPeriod.YEARLY:
        return amount
    if period is SalaryPeriod.MONTHLY:
        return amount * _MONTHS_PER_YEAR
    return amount * _HOURS_PER_YEAR


def score_salary(
    *,
    job_salary_min: Decimal | None,
    job_salary_max: Decimal | None,
    job_currency: str | None,
    job_period: SalaryPeriod | None,
    candidate_minimum: Decimal | None,
    candidate_currency: str | None,
) -> DimensionScore:
    """Whether the posting clears what the candidate asked for.

    ml.md gives three cases: job max >= candidate minimum -> 1.0; overlap ->
    linear in the overlap fraction; nothing listed -> 0.5. The middle case reads
    oddly at first, because if the job's maximum clears the candidate's floor
    the ranges *do* overlap and the first case already returned 1.0. The only
    remaining case is a job that pays under the floor, and the honest linear
    reading of it is the shortfall ratio — `job_max / candidate_minimum` — which
    is 1.0 at the boundary and 0 at no pay. That is the reading implemented.

    **The candidate's floor is assumed to be yearly.** `Profile` has no period
    column, so there is nothing to read; the assumption is stated here and in
    the reason string is never presented as something the user told us.

    Currencies must agree. There is no conversion helper anywhere in this
    codebase and inventing a rate would produce a number that looks precise and
    is not, so a mismatch returns `NEEDS_DATA` rather than a wrong answer.
    """
    quoted = job_salary_max if job_salary_max is not None else job_salary_min
    if quoted is None:
        # 245 of 256 postings. Treating it as a zero would penalise almost the
        # entire corpus for something unrelated to fit (ml.md section 4.1).
        return _stated(NEUTRAL, "This posting doesn't list a salary, so this counts as neutral.")

    if candidate_minimum is None:
        return _unknown(
            DimensionStatus.NEEDS_PROFILE,
            "You haven't set a minimum salary, so this counts as neutral. "
            "Add one to your profile.",
        )

    if job_currency is None or candidate_currency is None:
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "We can't tell what currency this salary is in, so this counts as neutral.",
        )
    if job_currency.upper() != candidate_currency.upper():
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "This salary is quoted in a different currency to yours and we don't "
            "convert between them, so this counts as neutral.",
        )

    yearly = _to_yearly(quoted, job_period)
    if yearly is None:
        return _unknown(
            DimensionStatus.NEEDS_DATA,
            "This posting doesn't say whether its salary is hourly, monthly or "
            "yearly, so this counts as neutral.",
        )

    if yearly >= candidate_minimum:
        return _scored(ONE, "This role's salary meets what you're looking for.")

    ratio = yearly / candidate_minimum if candidate_minimum > 0 else ONE
    return _scored(
        min(ONE, max(ZERO, ratio)),
        "This role's top salary is below the minimum on your profile.",
    )
