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
    #: Curated prerequisites that are also steps in this path, by name.
    #:
    #: Only the ones being learned here. A prerequisite the reader already holds
    #: is satisfied and saying so would clutter the reason with a non-reason.
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    steps: list[PlannedStep]
    total_hours: int
    #: Gaps with no curated guidance, so the omission is visible.
    skipped_uncurated: int


def build_plan(gaps: list[SkillGap]) -> Plan:
    """Order the missing skills so that nothing is asked for before its basis.

    Takes the gap list rather than querying, so the ordering is pure and can be
    tested without a database — and so the single-job and target-role paths are
    built by identical code.
    """
    held = {gap.name for gap in gaps if gap.status is GapStatus.STRONG}
    # PARTIAL counts as unsatisfied. Having something adjacent to a prerequisite
    # is not having the prerequisite, and assuming otherwise would order a step
    # before its foundation on the strength of a taxonomy sibling.
    wanted = [gap for gap in gaps if gap.status is GapStatus.MISSING]

    curated = [gap for gap in wanted if gap.name in CURATED]
    skipped = len(wanted) - len(curated)

    by_name = {gap.name: gap for gap in curated}
    remaining = dict(by_name)

    steps: list[PlannedStep] = []
    position = 1

    while remaining:
        # Everything whose curated prerequisites are either already held or
        # already placed in this path.
        placed = {step.name for step in steps}
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
        curated_step = CURATED[best.name]

        steps.append(
            PlannedStep(
                position=position,
                skill_id=best.skill_id,
                name=best.name,
                severity=best.severity.value,
                hours=curated_step.hours,
                outcome=curated_step.outcome,
                after=tuple(p for p in curated_step.prerequisites if p in by_name),
            )
        )
        position += 1
        del remaining[best.name]

    return Plan(
        steps=steps,
        total_hours=sum(step.hours for step in steps),
        skipped_uncurated=skipped,
    )
