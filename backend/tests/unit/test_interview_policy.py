"""What the interview asks next (ADR-013).

Exhaustive is achievable here and worth doing. `next_action` is pure -- no
database, no clock, no model -- so the whole cross-product of difficulty, score
band and state fits in one file with nothing stubbed, which is the property
ADR-013 chose a deterministic policy to get.
"""

from __future__ import annotations

import pytest

from app.models.enums import QuestionDifficulty as D
from app.services.interview.policy import (
    BLUEPRINTS,
    LADDER,
    STRONG_AT_OR_ABOVE,
    STRUGGLING_BELOW,
    Action,
    InterviewState,
    Move,
    easier,
    harder,
    next_action,
    next_topic,
)

TOPICS = BLUEPRINTS["DEFAULT"]


def state(
    *,
    difficulty: D = D.MEDIUM,
    covered: tuple[str, ...] = (),
    asked: int = 1,
    budget: int = 10,
) -> InterviewState:
    return InterviewState(
        current_difficulty=difficulty,
        topics_covered=covered,
        questions_asked=asked,
        question_budget=budget,
    )


class TestTheLadder:
    """Difficulty moves one rung and clamps, rather than erroring at the ends."""

    @pytest.mark.parametrize("rung", LADDER)
    def test_every_rung_has_a_neighbour_in_both_directions(self, rung: D) -> None:
        # No rung may raise. A struggling candidate at EASY needs another
        # question, not a crash, and somebody acing EXPERT has made the point.
        assert easier(rung) in LADDER
        assert harder(rung) in LADDER

    def test_easier_stops_at_the_bottom(self) -> None:
        assert easier(D.EASY) is D.EASY
        assert easier(D.MEDIUM) is D.EASY

    def test_harder_stops_at_the_top(self) -> None:
        assert harder(D.EXPERT) is D.EXPERT
        assert harder(D.HARD) is D.EXPERT


class TestBudget:
    """The budget is checked before the score, and that ordering is the point."""

    @pytest.mark.parametrize("score", [0.0, 0.39, 0.4, 0.69, 0.7, 1.0])
    def test_a_spent_budget_finishes_whatever_the_score(self, score: float) -> None:
        """Including a final answer that scored well.

        Reading ADR-013's table top-down would let a 0.9 buy an eleventh
        question on a ten-question budget -- a bug that only ever appears for
        the users doing best, which is the worst kind to ship.
        """
        finished = next_action(state(asked=10, budget=10), score)

        assert finished == Action(move=Move.FINISH, topic=None, difficulty=None)

    def test_one_question_short_still_asks(self) -> None:
        assert next_action(state(asked=9, budget=10), 0.9).move is not Move.FINISH

    def test_over_budget_finishes_rather_than_looping(self) -> None:
        # `>=` not `==`: a budget lowered mid-session, or a double-write, must
        # still terminate rather than run forever past the number.
        assert next_action(state(asked=11, budget=10), 0.9).move is Move.FINISH


class TestScoreBands:
    """ADR-013's three bands, and the two boundaries between them."""

    @pytest.mark.parametrize("score", [0.0, 0.1, 0.39, 0.399])
    def test_a_weak_answer_gets_an_easier_question_on_the_same_topic(
        self, score: float
    ) -> None:
        current = state(difficulty=D.HARD, covered=(TOPICS[0],))

        action = next_action(current, score)

        assert action.move is Move.CLARIFY
        assert action.difficulty is D.MEDIUM
        # Same topic. Moving on would leave the gap unexamined, which is the
        # opposite of what somebody rehearsing wants.
        assert action.topic == TOPICS[0]

    @pytest.mark.parametrize("score", [0.4, 0.5, 0.69, 0.699])
    def test_a_middling_answer_holds_difficulty_and_moves_topic(
        self, score: float
    ) -> None:
        current = state(difficulty=D.HARD, covered=(TOPICS[0],))

        action = next_action(current, score)

        assert action.move is Move.CONTINUE
        assert action.difficulty is D.HARD
        assert action.topic == TOPICS[1]

    @pytest.mark.parametrize("score", [0.7, 0.8, 1.0])
    def test_a_strong_answer_takes_a_fresh_topic_before_going_harder(
        self, score: float
    ) -> None:
        """Breadth before depth.

        ADR-013 offers both moves here. An interview that drills one topic to
        EXPERT has measured less about somebody than one that establishes
        competence across the blueprint, so an uncovered topic wins while one
        exists.
        """
        current = state(difficulty=D.MEDIUM, covered=(TOPICS[0],))

        action = next_action(current, score)

        assert action.move is Move.ADVANCE
        assert action.topic == TOPICS[1]
        assert action.difficulty is D.MEDIUM

    def test_the_boundaries_land_in_the_band_above(self) -> None:
        """0.4 and 0.7 exactly -- where a transcription error hides.

        ADR-013 writes the bands as `< 0.4`, `0.4 <=` and `>= 0.7`, so both
        boundary values belong to the *upper* band. A `<=` slipped in for a `<`
        moves them down one and nothing else in the suite would notice.
        """
        assert next_action(state(), STRUGGLING_BELOW).move is Move.CONTINUE
        assert next_action(state(), STRONG_AT_OR_ABOVE).move is Move.ADVANCE


class TestTopicsExhausted:
    """What happens once the blueprint is walked out."""

    def test_a_strong_answer_goes_harder_when_every_topic_is_covered(self) -> None:
        current = state(difficulty=D.MEDIUM, covered=TOPICS)

        action = next_action(current, 0.9)

        assert action.move is Move.ADVANCE
        assert action.difficulty is D.HARD
        assert action.topic == TOPICS[-1]

    def test_a_middling_answer_stays_put_rather_than_finishing_early(self) -> None:
        """Running out of topics is not a reason to end the interview.

        The budget is what terminates it. Ending early because the blueprint is
        short would make the interview's length depend on the topic list rather
        than on what the user asked for.
        """
        current = state(difficulty=D.MEDIUM, covered=TOPICS, asked=3, budget=10)

        action = next_action(current, 0.5)

        assert action.move is Move.CONTINUE
        assert action.topic == TOPICS[-1]
        assert action.difficulty is D.MEDIUM

    def test_next_topic_reports_nothing_left(self) -> None:
        assert next_topic(state(covered=TOPICS)) is None
        assert next_topic(state(covered=())) == TOPICS[0]

    def test_topics_are_walked_in_blueprint_order_not_arrival_order(self) -> None:
        """Two interviews for one role must walk the same path.

        Otherwise comparing them means nothing -- one person's third question
        would be about a different thing from another's.
        """
        # Covered out of order: the blueprint's second topic, then its first.
        current = state(covered=(TOPICS[1], TOPICS[0]))

        assert next_topic(current) == TOPICS[2]


class TestEveryCombination:
    """The full cross-product returns something usable.

    Not asserting the specific move here -- the classes above do that. This
    asserts the weaker, broader property: no combination of state and score
    raises, and none returns a half-formed action that a caller would then have
    to guard against.
    """

    @pytest.mark.parametrize("difficulty", LADDER)
    @pytest.mark.parametrize("score", [0.0, 0.39, 0.4, 0.69, 0.7, 1.0])
    @pytest.mark.parametrize("covered_count", range(len(TOPICS) + 1))
    def test_every_state_yields_a_coherent_action(
        self, difficulty: D, score: float, covered_count: int
    ) -> None:
        action = next_action(
            state(difficulty=difficulty, covered=TOPICS[:covered_count]), score
        )

        assert action.move in Move
        if action.move is Move.FINISH:
            assert action.topic is None
            assert action.difficulty is None
        else:
            # The invariant a caller depends on: anything that is not FINISH
            # carries both a topic and a difficulty, so generating a question
            # never has to invent a missing half.
            assert action.topic is not None
            assert action.difficulty in LADDER
