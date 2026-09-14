"""Turn skill gaps into an ordered study plan (US-5.2).

`compute_gaps` says what is missing and how much each one matters. This says what
order to do them in, which is a different question: the most urgent gap is often
not the one to start with, because it rests on something the reader also lacks.

## The ordering

US-5.2 AC1 asks for *"ordered by dependency (Docker before Kubernetes) and
severity"*. Both, in that priority:

1. **Dependency first, always.** A prerequisite is a hard constraint — being told
   to learn Kubernetes before Docker is not merely suboptimal advice, it is
   advice that does not work.
2. **Severity within what is currently unblocked.** Among the steps whose
   prerequisites are already satisfied, the one the target roles ask for most
   comes first.

That is a topological sort with severity as the tie-break, implemented as a
repeated "take the most urgent available step" rather than a sort followed by a
fix-up. Sorting by severity and then repairing the order would produce a
different answer depending on the starting list, and the repair is where the
subtle bug lives.

## Prerequisites the reader already has are not steps

If someone knows Docker, the Kubernetes step is unblocked and Docker never
appears. The path is what is left to do, not a curriculum from zero — a plan that
opens with something you can already do is one a reader stops trusting.

## Uncurated gaps produce no step

`data/learning.py` explains why: a generic outcome is not a concrete one, and
padding the plan with "learn X, 12 hours, be able to use X" makes the real steps
harder to trust. The count of skipped gaps is returned so the omission is visible
rather than silent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.data.learning import CURATED
from app.services.skill.gaps import GapStatus, SkillGap

#: Ordering weight per severity. Higher is more urgent.
_SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """One skill to learn, in the order it should be learned."""

    position: int
    skill_id: uuid.UUID
    name: str
    severity: str
    hours: int
    outcome: str
    #: The user has ticked this off.
    #:
    #: A completed step stays *in* the plan rather than disappearing. The list is
    #: a route someone is walking, and silently dropping the parts they have done
    #: would remove the only evidence of progress they have.
    completed: bool
    #: Curated prerequisites that are also steps in this path, by name.
    #:
    #: Only the ones being learned here. A prerequisite the reader already holds
    #: is satisfied and saying so would clutter the reason with a non-reason.
    #:
    #: A *ticked* prerequisite does still appear, because it is still a step on
    #: this page — shown, struck through, directly above. Naming it explains the
    #: ordering rather than stating a non-reason, which is the opposite of the
    #: case above: there the prerequisite is nowhere to be seen.
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    steps: list[PlannedStep]
    total_hours: int
    #: Gaps with no curated guidance, so the omission is visible.
    skipped_uncurated: int
    #: Hours left once ticked-off steps are discounted.
    #:
    #: Reported next to `total_hours` rather than replacing it: "180 of 677
    #: hours remaining" says something "180 hours" alone does not.
    remaining_hours: int


def build_plan(gaps: list[SkillGap], *, completed_skill_ids: set[uuid.UUID] | None = None) -> Plan:
    """Order the missing skills so that nothing is asked for before its basis.

    Takes the gap list rather than querying, so the ordering is pure and can be
    tested without a database — and so the single-job and target-role paths are
    built by identical code.

    `completed_skill_ids` are steps the user has ticked off. They stay in the
    plan, marked, and they **satisfy prerequisites**: someone who has studied
    Docker is ready for Kubernetes whether or not Docker is on their profile
    yet. Studying a thing and claiming it on a resume are different assertions,
    and requiring the second before unblocking the next step would leave a reader
    stuck behind their own honesty.
    """
    done = completed_skill_ids or set()
    held = {gap.name for gap in gaps if gap.status is GapStatus.STRONG}
    held |= {gap.name for gap in gaps if gap.skill_id in done}
    # PARTIAL counts as unsatisfied. Having something adjacent to a prerequisite
    # is not having the prerequisite, and assuming otherwise would order a step
    # before its foundation on the strength of a taxonomy sibling.
    wanted = [gap for gap in gaps if gap.status is GapStatus.MISSING]

    curated = [gap for gap in wanted if gap.name in CURATED]
    skipped = len(wanted) - len(curated)

    by_name = {gap.name: gap for gap in curated}
    remaining = dict(by_name)

    ordered: list[SkillGap] = []

    while remaining:
        # Everything whose curated prerequisites are either already held or
        # already placed in this path.
        placed = {gap.name for gap in ordered}
        available = [
            gap
            for name, gap in remaining.items()
            if all(p in held or p in placed for p in CURATED[name].prerequisites)
        ]

        if not available:
            # Unreachable while the curation has no cycles — a unit test pins
            # that — but a silent infinite loop is the worst possible failure
            # here, so the remaining steps are appended in severity order rather
            # than spinning. Order is then wrong, which is visible; hanging is
            # not.
            available = list(remaining.values())

        # `min` over negated numbers rather than `max`, so the final tie-break
        # runs alphabetically *forwards*. With `max` the name comparison would
        # favour Z over A, which is deterministic but reads as random to anyone
        # looking at two equally urgent steps.
        best = min(
            available,
            key=lambda g: (-_SEVERITY_RANK.get(g.severity.value, 0), -g.frequency, g.name),
        )
        ordered.append(best)
        del remaining[best.name]

    # Finished steps first, each group keeping its dependency order.
    #
    # Not cosmetic. A completed step satisfies its dependants' prerequisites, so
    # they become available immediately and a more urgent one can win the pass
    # that would otherwise have gone to the step it depends on — leaving a plan
    # reading "1. Kubernetes, 2. Docker (done)". Sorting the done work to the
    # front keeps every prerequisite above the thing that needs it, and matches
    # how the plan reads: what you have finished, then what is left.
    ordered.sort(key=lambda gap: gap.skill_id not in done)

    steps = [
        PlannedStep(
            position=index,
            skill_id=gap.skill_id,
            name=gap.name,
            severity=gap.severity.value,
            hours=CURATED[gap.name].hours,
            outcome=CURATED[gap.name].outcome,
            completed=gap.skill_id in done,
            after=tuple(p for p in CURATED[gap.name].prerequisites if p in by_name),
        )
        for index, gap in enumerate(ordered, start=1)
    ]

    return Plan(
        steps=steps,
        total_hours=sum(step.hours for step in steps),
        skipped_uncurated=skipped,
        remaining_hours=sum(step.hours for step in steps if not step.completed),
    )
