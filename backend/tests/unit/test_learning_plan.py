"""Ordering a study plan (US-5.2 AC1).

Pure, so it is tested without a database. The ordering is the whole feature —
telling someone to learn Kubernetes before Docker is not suboptimal advice, it is
advice that does not work — and it is exactly the kind of logic that looks right
and is wrong on a case nobody tried.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.services.skill.gaps import GapSeverity, GapStatus, SkillGap
from app.services.skill.learning import build_plan


def gap(
    name: str,
    *,
    status: GapStatus = GapStatus.MISSING,
    severity: GapSeverity = GapSeverity.MEDIUM,
    frequency: str = "0.30",
) -> SkillGap:
    return SkillGap(
        skill_id=uuid.uuid4(),
        name=name,
        category="tool",
        status=status,
        severity=severity,
        frequency=Decimal(frequency),
        job_count=5,
    )


def order(plan) -> list[str]:
    return [step.name for step in plan.steps]


class TestDependencyOrder:
    def test_a_prerequisite_comes_first_even_when_less_urgent(self) -> None:
        """The case US-5.2 names, and the one that matters.

        Kubernetes is the more urgent gap here. Ordering by severity alone would
        put it first and hand the reader a plan they cannot follow.
        """
        plan = build_plan(
            [
                gap("Kubernetes", severity=GapSeverity.CRITICAL, frequency="0.90"),
                gap("Docker", severity=GapSeverity.LOW, frequency="0.10"),
            ]
        )

        assert order(plan) == ["Docker", "Kubernetes"]

    def test_a_chain_is_resolved_end_to_end(self) -> None:
        # RAG needs Embeddings and Large Language Models; both need Python.
        plan = build_plan(
            [
                gap("RAG", severity=GapSeverity.CRITICAL),
                gap("Embeddings"),
                gap("Large Language Models"),
                gap("Python", severity=GapSeverity.LOW),
            ]
        )

        names = order(plan)
        assert names.index("Python") < names.index("Embeddings")
        assert names.index("Python") < names.index("Large Language Models")
        assert names.index("Embeddings") < names.index("RAG")
        assert names.index("Large Language Models") < names.index("RAG")

    def test_a_prerequisite_the_reader_already_has_is_not_a_step(self) -> None:
        """A plan that opens with something you can already do is one a reader
        stops trusting."""
        plan = build_plan(
            [
                gap("Kubernetes", severity=GapSeverity.HIGH),
                gap("Docker", status=GapStatus.STRONG),
            ]
        )

        assert order(plan) == ["Kubernetes"]
        # ...and the step does not claim to depend on a step that is not here.
        assert plan.steps[0].after == ()

    def test_a_related_skill_does_not_satisfy_a_prerequisite(self) -> None:
        """PARTIAL is not STRONG.

        Having something adjacent in the taxonomy is not having the thing, and
        treating it as satisfied would order a step before its foundation on the
        strength of a sibling.
        """
        plan = build_plan(
            [
                gap("Kubernetes", severity=GapSeverity.CRITICAL),
                gap("Docker", status=GapStatus.PARTIAL),
            ]
        )

        # Docker is PARTIAL, so it is not a MISSING gap and gets no step — but it
        # is also not *held*, so Kubernetes must not be treated as unblocked by
        # it. The plan contains only Kubernetes, and that is the honest answer:
        # the reader is told what is missing, and Docker is not missing.
        assert order(plan) == ["Kubernetes"]


class TestTickingAStepOff:
    """What a completion does to the plan.

    Ticking a step is the user saying "I have studied this". That is a different
    assertion from "this is on my resume", and the plan has to honour the first
    without waiting for the second.
    """

    def test_a_studied_prerequisite_unblocks_what_follows(self) -> None:
        """The central claim of US-5.2's checkbox.

        Docker is ticked but still missing from the profile — nobody updates a
        resume the moment they finish a tutorial. If a completion did not satisfy
        the prerequisite, Kubernetes would stay blocked behind a step the reader
        has already done, leaving them stuck behind their own honesty.

        Redis is here to make the claim measurable. With only Docker and
        Kubernetes the order is "Docker, Kubernetes" either way — as a
        prerequisite if the completion counts, and as a finished step sorted to
        the front if it does not — so the two behaviours are indistinguishable.
        A third, unrelated, *more* urgent step separates them: Kubernetes can
        only outrank Redis if it is unblocked on the first pass.
        """
        docker = gap("Docker", severity=GapSeverity.LOW, frequency="0.10")
        kubernetes = gap("Kubernetes", severity=GapSeverity.CRITICAL, frequency="0.90")
        redis = gap("Redis", severity=GapSeverity.HIGH, frequency="0.50")

        plan = build_plan([kubernetes, redis, docker], completed_skill_ids={docker.skill_id})

        steps = {step.name: step for step in plan.steps}
        assert steps["Docker"].completed is True
        assert steps["Kubernetes"].completed is False
        # Kubernetes beats Redis on severity, which it can only do from the first
        # pass — i.e. only if the tick satisfied its prerequisite.
        assert order(plan) == ["Docker", "Kubernetes", "Redis"]

    def test_a_finished_step_stays_in_the_plan(self) -> None:
        """The list is a route being walked. Dropping the finished parts removes
        the only evidence of progress there is."""
        docker = gap("Docker")

        plan = build_plan([docker], completed_skill_ids={docker.skill_id})

        assert order(plan) == ["Docker"]
        assert plan.steps[0].completed is True

    def test_hours_left_discount_what_is_done_but_the_total_does_not(self) -> None:
        """Both numbers are reported: "20 of 60 hours left" says something "20
        hours" alone does not."""
        docker = gap("Docker")
        kubernetes = gap("Kubernetes")

        plan = build_plan([kubernetes, docker], completed_skill_ids={docker.skill_id})

        done_hours = next(s.hours for s in plan.steps if s.name == "Docker")
        assert plan.total_hours == sum(step.hours for step in plan.steps)
        assert plan.remaining_hours == plan.total_hours - done_hours

    def test_no_completions_is_the_same_plan_as_before(self) -> None:
        """The argument is optional, and absent it must change nothing — every
        other test in this file calls `build_plan` without it."""
        gaps = [
            gap("Kubernetes", severity=GapSeverity.CRITICAL, frequency="0.90"),
            gap("Docker", severity=GapSeverity.LOW, frequency="0.10"),
        ]

        assert order(build_plan(gaps, completed_skill_ids=set())) == order(build_plan(gaps))
        assert order(build_plan(gaps, completed_skill_ids=None)) == ["Docker", "Kubernetes"]


class TestSeverityWithinWhatIsUnblocked:
    def test_the_most_urgent_available_step_comes_first(self) -> None:
        plan = build_plan(
            [
                gap("Git", severity=GapSeverity.LOW, frequency="0.10"),
                gap("SQL", severity=GapSeverity.CRITICAL, frequency="0.80"),
                gap("Docker", severity=GapSeverity.MEDIUM, frequency="0.40"),
            ]
        )

        assert order(plan) == ["SQL", "Docker", "Git"]

    def test_frequency_breaks_a_severity_tie(self) -> None:
        plan = build_plan(
            [
                gap("Git", severity=GapSeverity.HIGH, frequency="0.40"),
                gap("Docker", severity=GapSeverity.HIGH, frequency="0.70"),
            ]
        )

        assert order(plan) == ["Docker", "Git"]

    def test_the_last_tie_break_runs_alphabetically_forwards(self) -> None:
        # Deterministic *and* unsurprising: with `max` the name comparison would
        # have favoured Z over A, which reads as random.
        plan = build_plan(
            [
                gap("Redis", severity=GapSeverity.HIGH, frequency="0.50"),
                gap("Linux", severity=GapSeverity.HIGH, frequency="0.50"),
            ]
        )

        assert order(plan) == ["Linux", "Redis"]


class TestWhatIsLeftOut:
    def test_only_missing_skills_become_steps(self) -> None:
        plan = build_plan(
            [
                gap("Docker", status=GapStatus.STRONG),
                gap("Git", status=GapStatus.PARTIAL),
                gap("SQL", status=GapStatus.MISSING),
            ]
        )

        assert order(plan) == ["SQL"]

    def test_an_uncurated_gap_is_counted_rather_than_invented(self) -> None:
        """Padding the plan with "learn X, 12 hours, be able to use X" would make
        the real steps harder to trust. The omission is reported instead."""
        plan = build_plan([gap("Docker"), gap("Semantic Kernel"), gap("DSPy")])

        assert order(plan) == ["Docker"]
        assert plan.skipped_uncurated == 2

    def test_total_hours_sums_the_steps_that_exist(self) -> None:
        plan = build_plan([gap("Docker"), gap("Git")])

        assert plan.total_hours == sum(step.hours for step in plan.steps)
        assert plan.total_hours > 0

    def test_an_empty_gap_list_is_an_empty_plan(self) -> None:
        plan = build_plan([])

        assert plan.steps == []
        assert plan.total_hours == 0
        assert plan.skipped_uncurated == 0
