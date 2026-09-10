"""The six scorers, one boundary at a time.

Two of these are property tests and they carry most of the weight. The rest are
example-based, because the branches of a scoring formula are exactly the kind of
thing that goes wrong at a boundary and nowhere else.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.enums import EducationLevel, SalaryPeriod, SkillRequirement, WorkMode
from app.services.matching.dimensions import (
    _RARITY_FLOOR,
    DimensionScore,
    SkillRequirementInput,
    classify_skills,
    score_education,
    score_experience,
    score_location,
    score_salary,
    score_semantic,
    score_skill,
    skill_rarity,
    years_from_history,
)
from app.services.matching.weights import (
    CANDIDATE_JOB_COSINE_CEILING,
    CANDIDATE_JOB_COSINE_FLOOR,
    NEUTRAL,
    DimensionStatus,
)


def req(name: str, requirement: SkillRequirement = SkillRequirement.REQUIRED, sid=None):
    return SkillRequirementInput(
        skill_id=sid or uuid.uuid4(), name=name, requirement=requirement
    )


# --------------------------------------------------------------------- semantic


class TestSemantic:
    def test_the_measured_floor_scores_zero_and_the_ceiling_scores_one(self):
        assert score_semantic(CANDIDATE_JOB_COSINE_FLOOR).score == Decimal("0.0000")
        assert score_semantic(CANDIDATE_JOB_COSINE_CEILING).score == Decimal("1.0000")

    @pytest.mark.parametrize("cosine", [Decimal("0.218"), Decimal("0.0"), Decimal("-0.4")])
    def test_clamps_below_the_floor(self, cosine: Decimal):
        """The measured minimum is 0.218, well under the floor.

        Clamping is load-bearing rather than defensive: without it these produce
        a negative dimension score, and a negative contribution would make the
        breakdown's arithmetic look broken to anyone checking it.
        """
        assert score_semantic(cosine).score == Decimal("0.0000")

    def test_clamps_above_the_ceiling(self):
        assert score_semantic(Decimal("0.99")).score == Decimal("1.0000")

    def test_the_midpoint_of_the_measured_range_scores_a_half(self):
        midpoint = (CANDIDATE_JOB_COSINE_FLOOR + CANDIDATE_JOB_COSINE_CEILING) / 2
        assert score_semantic(midpoint).score == Decimal("0.5000")

    def test_no_vector_is_needs_data_not_needs_profile(self):
        """A resume the indexer has not reached yet is not the user's fault.

        The distinction is the whole reason the status enum has four members:
        NEEDS_PROFILE renders a call to action, and telling someone to fix a
        profile that is already complete is worse than saying nothing.
        """
        result = score_semantic(None)
        assert result.status is DimensionStatus.NEEDS_DATA
        assert result.score == NEUTRAL

    def test_never_prints_the_number(self):
        """R4: the reason describes the strength of a resemblance, never its
        substance, and never quotes the cosine itself.

        Swept across the whole legal cosine range rather than spot-checked,
        because the phrasing is banded and a digit could hide in any one band.
        """
        for step in range(-100, 101):
            cosine = Decimal(step) / 100
            reason = score_semantic(cosine).reason
            assert not re.search(r"\d", reason), (cosine, reason)


# ------------------------------------------------------------------------ skill


class TestSkill:
    def test_all_required_skills_held_scores_one(self):
        a, b = req("Python"), req("PostgreSQL")
        buckets = classify_skills(
            requirements=[a, b],
            candidate_skill_ids=[a.skill_id, b.skill_id],
            parent_of={},
        )
        result = score_skill(buckets=buckets, has_candidate_skills=True)
        assert result.score == Decimal("1.0000")
        assert result.status is DimensionStatus.SCORED

    def test_preferred_skills_weigh_half_as_much_as_required(self):
        """One REQUIRED held and one PREFERRED missing is 1.0 / 1.5, not 0.5."""
        held = req("Python", SkillRequirement.REQUIRED)
        missing = req("Kubernetes", SkillRequirement.PREFERRED)
        buckets = classify_skills(
            requirements=[held, missing],
            candidate_skill_ids=[held.skill_id],
            parent_of={},
        )
        assert score_skill(buckets=buckets, has_candidate_skills=True).score == Decimal("0.6667")

    def test_a_parent_the_candidate_holds_is_a_partial_match(self):
        """The job wants React; the candidate listed JavaScript."""
        javascript = uuid.uuid4()
        react = req("React", sid=uuid.uuid4())
        buckets = classify_skills(
            requirements=[react],
            candidate_skill_ids=[javascript],
            parent_of={react.skill_id: javascript},
        )
        assert buckets.partial == (react,)
        assert score_skill(buckets=buckets, has_candidate_skills=True).score == Decimal("0.5000")

    def test_a_child_the_candidate_holds_is_a_partial_match(self):
        """The reverse direction: the job wants JavaScript, they listed React."""
        javascript = req("JavaScript")
        react = uuid.uuid4()
        buckets = classify_skills(
            requirements=[javascript],
            candidate_skill_ids=[react],
            parent_of={react: javascript.skill_id},
        )
        assert buckets.partial == (javascript,)

    def test_a_grandparent_is_not_credited(self):
        """One level only.

        The taxonomy is genuinely multi-level — BCDU-Net -> U-Net -> ... ->
        Machine Learning — so crediting any ancestor would score someone who
        listed one segmentation architecture as knowing Machine Learning
        outright. That is a claim about a person we cannot support (ADR-012).
        """
        grandparent = uuid.uuid4()
        parent = uuid.uuid4()
        child = req("BCDU-Net")
        buckets = classify_skills(
            requirements=[child],
            candidate_skill_ids=[grandparent],
            parent_of={child.skill_id: parent, parent: grandparent},
        )
        assert buckets.missing == (child,)

    def test_an_empty_profile_and_a_profile_that_matches_nothing_are_different(self):
        """Same three buckets, different facts, different statuses.

        A user whose skills simply do not overlap has a real score of zero and
        must not be told to go and fix something.
        """
        wanted = req("COBOL")
        empty = classify_skills(requirements=[wanted], candidate_skill_ids=[], parent_of={})
        assert score_skill(buckets=empty, has_candidate_skills=False).status is (
            DimensionStatus.NEEDS_PROFILE
        )

        unrelated = classify_skills(
            requirements=[wanted], candidate_skill_ids=[uuid.uuid4()], parent_of={}
        )
        scored = score_skill(buckets=unrelated, has_candidate_skills=True)
        assert scored.status is DimensionStatus.SCORED
        assert scored.score == Decimal("0.0000")

    def test_a_posting_with_no_skill_rows_is_needs_data(self):
        buckets = classify_skills(
            requirements=[], candidate_skill_ids=[uuid.uuid4()], parent_of={}
        )
        assert score_skill(buckets=buckets, has_candidate_skills=True).status is (
            DimensionStatus.NEEDS_DATA
        )

    def test_the_reason_names_the_skills(self):
        held = req("Python")
        buckets = classify_skills(
            requirements=[held, req("Kubernetes")],
            candidate_skill_ids=[held.skill_id],
            parent_of={},
        )
        reason = score_skill(buckets=buckets, has_candidate_skills=True).reason
        assert "Python" in reason
        assert "2 skills" in reason

    def test_a_long_list_is_truncated_rather_than_inventoried(self):
        names = ["Python", "Go", "Rust", "Java", "Scala", "Elixir"]
        held = [req(name) for name in names]
        buckets = classify_skills(
            requirements=held,
            candidate_skill_ids=[r.skill_id for r in held],
            parent_of={},
        )
        reason = score_skill(buckets=buckets, has_candidate_skills=True).reason
        assert "and 2 more" in reason
        assert "Elixir" not in reason


# ------------------------------------------------------------------- experience


class TestExperience:
    def test_a_job_stating_nothing_awards_full_marks_but_is_not_scored(self):
        """Absence of a requirement is not a penalty — but it is not evidence
        about this person either, so it must not count toward `scored_weight`."""
        result = score_experience(
            candidate_years=Decimal("3"), min_years=None, max_years=None
        )
        assert result.score == Decimal("1.0000")
        assert result.status is DimensionStatus.NOT_STATED

    def test_unknown_candidate_years_is_needs_profile(self):
        result = score_experience(
            candidate_years=None, min_years=Decimal("3"), max_years=Decimal("6")
        )
        assert result.status is DimensionStatus.NEEDS_PROFILE
        assert result.score == NEUTRAL

    @pytest.mark.parametrize(
        ("years", "expected"),
        [
            (Decimal("3"), Decimal("1.0000")),  # exactly at the minimum
            (Decimal("4.5"), Decimal("1.0000")),  # inside
            (Decimal("6"), Decimal("1.0000")),  # exactly at the maximum
            (Decimal("1.5"), Decimal("0.5000")),  # half the minimum
            (Decimal("0"), Decimal("0.0000")),  # none at all
        ],
    )
    def test_the_below_minimum_curve(self, years: Decimal, expected: Decimal):
        result = score_experience(
            candidate_years=years, min_years=Decimal("3"), max_years=Decimal("6")
        )
        assert result.score == expected

    @pytest.mark.parametrize(
        ("years", "expected"),
        [
            (Decimal("7"), Decimal("0.9500")),  # one year over
            (Decimal("12"), Decimal("0.7000")),  # six years over, at the floor
            (Decimal("30"), Decimal("0.7000")),  # far over, still the floor
        ],
    )
    def test_being_over_experienced_is_a_mild_signal_not_a_disqualification(
        self, years: Decimal, expected: Decimal
    ):
        """Asymmetric by design (ml.md section 4.1).

        A symmetric penalty would bury senior candidates on roles they would
        walk into, which is the failure mode this curve exists to avoid.
        """
        result = score_experience(
            candidate_years=years, min_years=Decimal("3"), max_years=Decimal("6")
        )
        assert result.score == expected

    def test_a_stated_zero_years_is_not_treated_as_unknown(self):
        """A fresher who says "none" told us something.

        The trap is `candidate_years or fallback`, which discards a legitimate
        Decimal("0"). It would show a career-changer a NEEDS_PROFILE row for a
        field they had already filled in.
        """
        result = score_experience(
            candidate_years=Decimal("0"), min_years=Decimal("2"), max_years=None
        )
        assert result.status is DimensionStatus.SCORED
        assert result.score == Decimal("0.0000")


class TestYearsFromHistory:
    def test_sums_spans_rather_than_spanning_the_gaps(self):
        """Two years, a two-year gap, then one year is three years of work."""
        entries = [
            (date(2018, 1, 1), date(2020, 1, 1), False),
            (date(2022, 1, 1), date(2023, 1, 1), False),
        ]
        assert years_from_history(entries, today=date(2026, 1, 1)) == Decimal("3.0")

    def test_a_current_role_runs_to_today(self):
        entries = [(date(2024, 1, 1), None, True)]
        assert years_from_history(entries, today=date(2026, 1, 1)) == Decimal("2.0")

    def test_no_usable_rows_gives_none_rather_than_zero(self):
        """`None` means "we don't know", `0` means "they have none".

        Returning zero here would score a user with an unparsed work history as
        having no experience at all — a confident, wrong statement about them.
        """
        assert years_from_history([], today=date(2026, 1, 1)) is None
        assert years_from_history([(None, None, False)], today=date(2026, 1, 1)) is None


# -------------------------------------------------------------------- education


class TestEducation:
    def test_a_job_stating_nothing_awards_full_marks_but_is_not_scored(self):
        result = score_education(candidate_level=None, required_level=None)
        assert result.score == Decimal("1.0000")
        assert result.status is DimensionStatus.NOT_STATED

    def test_unknown_candidate_education_is_needs_profile(self):
        """Asserted separately from the branch above, deliberately.

        Collapsing "the job didn't say" into "we don't know about you" is
        exactly what produces a call to action for something the user has no
        power over.
        """
        result = score_education(
            candidate_level=None, required_level=EducationLevel.BACHELORS
        )
        assert result.status is DimensionStatus.NEEDS_PROFILE
        assert result.score == NEUTRAL

    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            (EducationLevel.DOCTORATE, Decimal("1.0000")),
            (EducationLevel.MASTERS, Decimal("1.0000")),
            (EducationLevel.BACHELORS, Decimal("1.0000")),  # exactly meets it
            (EducationLevel.DIPLOMA, Decimal("0.6000")),  # one below
            (EducationLevel.HIGH_SCHOOL, Decimal("0.2000")),  # two below
            (EducationLevel.NONE, Decimal("0.2000")),  # three below, same floor
        ],
    )
    def test_ordinal_comparison_against_a_bachelors_requirement(
        self, candidate: EducationLevel, expected: Decimal
    ):
        result = score_education(
            candidate_level=candidate, required_level=EducationLevel.BACHELORS
        )
        assert result.score == expected


# --------------------------------------------------------------------- location


def location(**overrides) -> DimensionScore:
    kwargs = {
        "job_location": "Bengaluru, Karnataka, IN",
        "job_country": "IN",
        "job_work_mode": WorkMode.ONSITE,
        "candidate_location": None,
        "candidate_country": "IN",
        "preferred_locations": ["Bengaluru"],
        "preferred_work_modes": [],
        "open_to_relocation": False,
    }
    kwargs.update(overrides)
    return score_location(**kwargs)  # type: ignore[arg-type]


class TestLocation:
    def test_a_listed_place_scores_one(self):
        assert location().score == Decimal("1.0000")

    def test_a_remote_role_matches_a_remote_preference(self):
        assert location(
            job_work_mode=WorkMode.REMOTE,
            job_location="India",
            preferred_locations=["Chennai"],
            preferred_work_modes=[WorkMode.REMOTE],
        ).score == Decimal("1.0000")

    def test_the_word_remote_inside_preferred_locations_is_read_as_a_work_mode(self):
        """One real profile has "Remote" in `preferred_locations`.

        That is a work mode in a places array. Matching it against a city name
        would be nonsense, so it is lifted out and read as what it plainly is.
        """
        assert location(
            job_work_mode=WorkMode.REMOTE,
            preferred_locations=["Remote"],
        ).score == Decimal("1.0000")

    def test_a_work_mode_word_is_not_matched_as_a_place_name(self):
        """The other half of the same rule: a remote *preference* must not make
        an onsite job in an unlisted city score as a location match."""
        assert location(
            job_location="Remote, Hyderabad",
            job_work_mode=WorkMode.ONSITE,
            preferred_locations=["Remote"],
        ).score != Decimal("1.0000")

    def test_same_country_scores_higher_when_open_to_relocation(self):
        assert location(
            job_location="Hyderabad, Telangana, IN", open_to_relocation=True
        ).score == Decimal("0.7000")
        assert location(
            job_location="Hyderabad, Telangana, IN", open_to_relocation=False
        ).score == Decimal("0.3000")

    def test_a_different_country_scores_lowest(self):
        assert location(
            job_location="Berlin, DE", job_country="DE"
        ).score == Decimal("0.1000")

    def test_feed_noise_is_not_read_as_a_place(self):
        """`India | Type: Full-Time` arrives in the location field verbatim."""
        assert location(
            job_location="Hyderabad | Type: Full-Time",
            preferred_locations=["Type: Full-Time"],
            open_to_relocation=True,
        ).score == Decimal("0.7000")

    def test_no_preferences_at_all_is_needs_profile(self):
        result = location(
            candidate_country=None, preferred_locations=[], preferred_work_modes=[]
        )
        assert result.status is DimensionStatus.NEEDS_PROFILE

    def test_a_posting_with_no_location_is_needs_data(self):
        result = location(job_location=None, job_country=None)
        assert result.status is DimensionStatus.NEEDS_DATA


# ----------------------------------------------------------------------- salary


def salary(**overrides) -> DimensionScore:
    kwargs = {
        "job_salary_min": Decimal("1200000"),
        "job_salary_max": Decimal("1800000"),
        "job_currency": "INR",
        "job_period": SalaryPeriod.YEARLY,
        "candidate_minimum": Decimal("1500000"),
        "candidate_currency": "INR",
    }
    kwargs.update(overrides)
    return score_salary(**kwargs)  # type: ignore[arg-type]


class TestSalary:
    def test_a_top_end_clearing_the_floor_scores_one(self):
        assert salary().score == Decimal("1.0000")

    def test_a_posting_below_the_floor_scores_the_shortfall_ratio(self):
        assert salary(job_salary_max=Decimal("750000")).score == Decimal("0.5000")

    def test_a_monthly_figure_is_normalised_before_comparing(self):
        """The trap this exists to avoid: reading a monthly Indian salary as an
        annual one understates it twelvefold and drags the score down for a
        reason the user could never diagnose."""
        assert salary(
            job_salary_max=Decimal("150000"), job_period=SalaryPeriod.MONTHLY
        ).score == Decimal("1.0000")

    def test_a_missing_period_is_not_assumed_to_be_yearly(self):
        result = salary(job_period=None)
        assert result.status is DimensionStatus.NEEDS_DATA

    def test_mismatched_currencies_refuse_rather_than_guess(self):
        """There is no conversion helper anywhere in this codebase.

        Inventing a rate would produce a number that looks precise and is not.
        """
        result = salary(job_currency="USD")
        assert result.status is DimensionStatus.NEEDS_DATA
        assert result.score == NEUTRAL

    def test_a_posting_with_no_salary_is_not_stated_and_stays_neutral(self):
        """245 of 256 postings. Scoring this as a zero would penalise almost the
        whole corpus for something unrelated to fit."""
        result = salary(job_salary_min=None, job_salary_max=None)
        assert result.status is DimensionStatus.NOT_STATED
        assert result.score == NEUTRAL

    def test_no_stated_expectation_is_needs_profile(self):
        assert salary(candidate_minimum=None).status is DimensionStatus.NEEDS_PROFILE


# ----------------------------------------------------------- the R1 property


def _every_unknown_reason() -> list[str]:
    """One unknown-status result from every scorer that can produce one."""
    results = [
        score_semantic(None),
        score_skill(
            buckets=classify_skills(requirements=[], candidate_skill_ids=[], parent_of={}),
            has_candidate_skills=True,
        ),
        score_skill(
            buckets=classify_skills(
                requirements=[req("Python")], candidate_skill_ids=[], parent_of={}
            ),
            has_candidate_skills=False,
        ),
        score_experience(
            candidate_years=None, min_years=Decimal("3"), max_years=Decimal("6")
        ),
        score_education(candidate_level=None, required_level=EducationLevel.MASTERS),
        location(candidate_country=None, preferred_locations=[], preferred_work_modes=[]),
        location(job_location=None, job_country=None),
        salary(candidate_minimum=None),
        salary(job_currency="USD"),
        salary(job_period=None),
        salary(job_currency=None),
    ]
    return [r.reason for r in results if r.status is not DimensionStatus.SCORED]


def test_no_unknown_reason_states_a_number():
    """R1, structurally enforced.

    A dimension we could not compute must never produce a sentence containing a
    figure, because the only figures available to interpolate would be ones we
    do not hold. api.md's own worked example breaks this rule — it writes "You
    have 3.5 years" on a row that may have had no candidate years at all — and a
    confident fabricated sentence is the single largest correctness risk in this
    feature (ADR-012). Digits are a crude proxy and that is the point: the check
    cannot be satisfied by wording it more carefully.
    """
    offenders = [reason for reason in _every_unknown_reason() if re.search(r"\d", reason)]
    assert offenders == []


def test_every_unknown_reason_says_what_we_did_instead():
    """R2. A bare "not recorded" leaves a 5.0 contribution appearing from
    nowhere, and the breakdown then looks broken rather than honest."""
    for reason in _every_unknown_reason():
        assert "neutral" in reason, reason


class TestSkillRarity:
    """Weighting requirements by how rare they are in the live market.

    Added in the quality pass after Phase 6.4: the ablation showed the skill
    dimension was *subtracting* from NDCG@10, and the measured cause was
    dilution — jobs list 18.5 skills on average and the commonest are close to
    universal.
    """

    def test_no_demand_score_reproduces_the_flat_behaviour(self):
        """A fresh database has never run the recompute.

        The weighting must collapse to exactly what it replaced, or deploying
        this would silently change every score in an environment that cannot
        support it yet.
        """
        held, missing = req("Python"), req("COBOL")
        buckets = classify_skills(
            requirements=[held, missing], candidate_skill_ids=[held.skill_id], parent_of={}
        )
        flat = score_skill(buckets=buckets, has_candidate_skills=True)
        explicit_none = score_skill(
            buckets=buckets,
            has_candidate_skills=True,
            demand={held.skill_id: None, missing.skill_id: None},
        )
        assert flat.score == explicit_none.score == Decimal("0.5000")

    def test_a_rare_skill_you_have_outweighs_a_common_one_you_lack(self):
        """The whole point of the change.

        Under flat weights, holding one of two required skills always scores
        0.5 regardless of which. Missing a skill three quarters of the market
        asks for says far less about fit than missing a specialism.
        """
        rare, common = req("Rust"), req("Communication")
        buckets = classify_skills(
            requirements=[rare, common], candidate_skill_ids=[rare.skill_id], parent_of={}
        )
        result = score_skill(
            buckets=buckets,
            has_candidate_skills=True,
            demand={rare.skill_id: Decimal("0.02"), common.skill_id: Decimal("0.75")},
        )
        assert result.score > Decimal("0.8")

    def test_and_the_reverse_costs_you(self):
        rare, common = req("Rust"), req("Communication")
        buckets = classify_skills(
            requirements=[rare, common], candidate_skill_ids=[common.skill_id], parent_of={}
        )
        result = score_skill(
            buckets=buckets,
            has_candidate_skills=True,
            demand={rare.skill_id: Decimal("0.02"), common.skill_id: Decimal("0.75")},
        )
        assert result.score < Decimal("0.2")

    def test_rarity_rises_as_demand_falls(self):
        assert skill_rarity(Decimal("0.75")) < skill_rarity(Decimal("0.40"))
        assert skill_rarity(Decimal("0.40")) < skill_rarity(Decimal("0.05"))

    def test_a_universal_skill_is_worth_almost_nothing(self):
        # log(1/1) = 0. A requirement every posting names cannot separate one
        # candidate from another, and the weight says so.
        assert skill_rarity(Decimal("1.0")) == Decimal("0")

    def test_the_floor_caps_how_much_one_obscure_tag_can_dominate(self):
        """Without it, `demand` of 0 divides by zero and 0.0001 would decide the
        dimension by itself on the strength of being rare rather than important."""
        assert skill_rarity(Decimal("0")) == skill_rarity(Decimal("0.001"))
        assert skill_rarity(Decimal("0")) == skill_rarity(_RARITY_FLOOR)

    def test_a_posting_of_only_universal_skills_is_neutral_not_zero(self):
        """Every weight is zero, so there is no ratio to take.

        Scoring it 0 would tell the candidate they match nothing, when what
        actually happened is that the posting listed nothing discriminating.
        """
        everyday = req("Communication")
        buckets = classify_skills(
            requirements=[everyday], candidate_skill_ids=[uuid.uuid4()], parent_of={}
        )
        result = score_skill(
            buckets=buckets,
            has_candidate_skills=True,
            demand={everyday.skill_id: Decimal("1.0")},
        )
        assert result.status is DimensionStatus.NEEDS_DATA
        assert result.score == NEUTRAL

    def test_a_skill_absent_from_the_demand_map_falls_back_to_flat(self):
        # A job requiring a skill added since the last recompute must still be
        # scored, not skipped.
        held, unknown = req("Python"), req("BrandNewFramework")
        buckets = classify_skills(
            requirements=[held, unknown], candidate_skill_ids=[held.skill_id], parent_of={}
        )
        result = score_skill(
            buckets=buckets,
            has_candidate_skills=True,
            demand={held.skill_id: Decimal("0.5")},
        )
        assert result.status is DimensionStatus.SCORED
        assert Decimal("0") < result.score < Decimal("1")
