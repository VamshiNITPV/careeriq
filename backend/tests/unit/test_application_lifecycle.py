"""The application funnel's transition rules (US-7.1 AC1).

Pure, so these cover the rules exhaustively against the enum rather than
sampling a few paths. The property that matters most is the last class: nothing
here lets a status be reached that the user did not report.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from app.models.enums import ApplicationStatus as S
from app.services.application.lifecycle import (
    ACTIVE,
    FUNNEL,
    REOPEN_TO,
    TERMINAL,
    IllegalTransitionError,
    allowed_from,
    check,
    is_terminal,
    progress,
)


class TestTheChainAC1Describes:
    @pytest.mark.parametrize(
        ("current", "target"),
        list(pairwise(FUNNEL)),
        ids=lambda value: str(value),
    )
    def test_each_step_forward_is_allowed(self, current: S, target: S) -> None:
        check(current, target)

    @pytest.mark.parametrize("ending", sorted(TERMINAL))
    @pytest.mark.parametrize("active", sorted(ACTIVE))
    def test_either_ending_is_reachable_from_any_active_state(self, active: S, ending: S) -> None:
        """AC1, stated literally: "rejected and withdrawn reachable from any
        active state"."""
        check(active, ending)

    def test_the_funnel_covers_every_active_status(self) -> None:
        """A status outside the funnel would have no position and no ordering,
        and would drop out of the US-7.2 counts silently."""
        assert set(FUNNEL) == ACTIVE
        assert set(S) == ACTIVE | TERMINAL
        assert not ACTIVE & TERMINAL


class TestCorrections:
    def test_going_back_a_stage_is_allowed(self) -> None:
        """Not in AC1, and deliberate. People mis-tap, and refusing would leave
        deleting the application as the only way out — losing its history to
        recover from a typo."""
        check(S.INTERVIEW, S.APPLIED)

    def test_standing_still_is_not_a_transition(self) -> None:
        """Every row in the log should mean something happened. A no-op event is
        noise in the one record that has to stay readable."""
        for status in S:
            assert status not in allowed_from(status)

    @pytest.mark.parametrize("ending", sorted(TERMINAL))
    def test_a_stopped_application_can_be_reopened(self, ending: S) -> None:
        """A rejection gets reversed and a withdrawal reconsidered. Without this
        a mis-tap strands the row permanently."""
        assert allowed_from(ending) == frozenset({REOPEN_TO})
        check(ending, REOPEN_TO)

    def test_reopening_returns_to_applied_not_saved(self) -> None:
        """It was submitted. Sending it back to a bookmark would discard that,
        and guessing the stage it stopped at is something only the event log has
        evidence for."""
        assert REOPEN_TO is S.APPLIED

    @pytest.mark.parametrize("target", [S.SAVED, S.ASSESSMENT, S.INTERVIEW, S.OFFER])
    def test_a_stopped_application_cannot_jump_straight_back_into_the_funnel(
        self, target: S
    ) -> None:
        with pytest.raises(IllegalTransitionError):
            check(S.REJECTED, target)

    def test_one_ending_cannot_become_the_other(self) -> None:
        """Withdrawing and being rejected are different facts about what
        happened. Converting one to the other would rewrite history rather than
        record it."""
        with pytest.raises(IllegalTransitionError):
            check(S.REJECTED, S.WITHDRAWN)


class TestWhatItRefuses:
    def test_the_error_names_both_ends(self) -> None:
        """A caller turns this into a message, and "that move is not allowed"
        without saying which move is not actionable."""
        with pytest.raises(IllegalTransitionError) as caught:
            check(S.WITHDRAWN, S.OFFER)

        assert caught.value.current is S.WITHDRAWN
        assert caught.value.target is S.OFFER
        assert "WITHDRAWN" in str(caught.value)
        assert "OFFER" in str(caught.value)


class TestProgress:
    @pytest.mark.parametrize(("status", "expected"), list(enumerate(FUNNEL)))
    def test_an_active_status_has_a_position(self, status: int, expected: S) -> None:
        # parametrize hands back (index, member); the names read the other way
        # round because enumerate yields the position first.
        assert progress(expected) == status

    @pytest.mark.parametrize("ending", sorted(TERMINAL))
    def test_a_stopped_application_has_none(self, ending: S) -> None:
        """Not a position. An application rejected after an interview and one
        rejected the day it was sent stopped at different depths, and only the
        event log knows which — reporting either as a number would invent a fact
        the funnel counts would then use."""
        assert progress(ending) is None
        assert is_terminal(ending)
