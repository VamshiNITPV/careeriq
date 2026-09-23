"""What the interview asks next (ADR-013, ml.md section 7.2).

Pure: no database, no session, no clock, no provider. That is not tidiness, it
is the decision ADR-013 exists to make --

    The LLM generates question *text* for a given (topic, difficulty); the LLM
    does not decide the trajectory.

-- so the trajectory is arithmetic over four values and can be proven
exhaustively offline, while the model is only ever asked to write English. The
alternative the ADR rejects, letting the model carry its own state across turns,
is "unreliable, unauditable, and grows the context window until it degrades".

`services/application/lifecycle.py` is the same shape for the same reason and is
worth reading beside this.

## The table, from ADR-013

| Condition           | Next action                                  |
|---------------------|----------------------------------------------|
| score < 0.4         | easier clarifying follow-up, same topic      |
| 0.4 <= score < 0.7  | same difficulty, adjacent topic              |
| score >= 0.7        | harder, or move to an uncovered topic        |
| topic exhausted     | next topic in the role's blueprint           |
| budget reached      | terminate, generate report                   |

## Three things the table does not decide

It is a design sketch, not a specification, and transcribing it meant answering
questions it leaves open. Each is recorded here rather than buried:

**Budget is checked first, before the score.** A final answer scoring 0.9 must
end the interview, not earn an eleventh question on a ten-question budget.
Reading the table top-down would do the opposite, because the score rows come
first -- and an interview that runs one question past its budget every time
somebody does well is a bug that only appears for the users doing best.

**The ladder clamps at both ends.** "Easier" at EASY has no lower rung and
"harder" at EXPERT has no higher one. Both stay put rather than erroring: a
struggling candidate should get another EASY question on a fresh angle, not a
crash, and somebody acing EXPERT has proven the point already.

**"Adjacent topic" and "the role's blueprint" are undefined.** A blueprint is a
per-role list of topics to work through, and it arrives here already resolved:
`services/interview/blueprint.py` derives it from what postings for the role
actually demand, with `GENERIC_TOPICS` below as the answer when the corpus has
too little to say. Either way it is *data passed in*, never something this
module fetches, which is what keeps it testable against literals.

What a blueprint must never be is model-generated. Choosing which topics exist
is choosing the trajectory, and that is the one thing ADR-013 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.enums import QuestionDifficulty

#: The difficulty ladder, easiest first. Order is behaviour here, not display.
LADDER: tuple[QuestionDifficulty, ...] = (
    QuestionDifficulty.EASY,
    QuestionDifficulty.MEDIUM,
    QuestionDifficulty.HARD,
    QuestionDifficulty.EXPERT,
)

#: ADR-013's thresholds. Named because a bare 0.4 in a comparison is the kind of
#: number that gets changed in one place and not the other.
STRUGGLING_BELOW = 0.4
STRONG_AT_OR_ABOVE = 0.7

#: Used when nothing better is available. **Not the normal case.**
#:
#: `services/interview/blueprint.py` derives topics from what postings for the
#: role actually demand, and that is what an interview is normally examined
#: against. This list is the answer when the corpus holds too few matching
#: adverts to call anything "demand" -- and the caller is told which it got, so
#: a generic interview is never presented as a market-derived one.
#:
#: Kept here rather than in `blueprint.py` so this module remains usable and
#: testable with no database at all.
GENERIC_TOPICS: tuple[str, ...] = (
    "Experience and background",
    "Core technical knowledge",
    "System design",
    "Problem solving",
    "Collaboration and communication",
)


class Move(StrEnum):
    """What kind of step the policy chose. Recorded, so a report can explain."""

    #: Same topic, one rung easier. They are struggling and need a way in.
    CLARIFY = "CLARIFY"
    #: Same difficulty, next topic. Holding steady.
    CONTINUE = "CONTINUE"
    #: Fresh topic, or harder if none is left. Doing well.
    ADVANCE = "ADVANCE"
    #: The budget is spent. Terminate and report.
    FINISH = "FINISH"


@dataclass(frozen=True, slots=True)
class InterviewState:
    """The state machine's variables, exactly as `interviews` stores them."""

    current_difficulty: QuestionDifficulty
    topics_covered: tuple[str, ...]
    questions_asked: int
    question_budget: int
    #: The topics to work through, already resolved, in the order to ask them.
    #:
    #: **Injected rather than looked up**, which is what keeps this module pure.
    #: 9.1 held a role key and consulted a static map here; that put a data
    #: source inside a function whose whole value is having none. The service
    #: resolves the blueprint -- from real demand where there is any -- and this
    #: only walks it.
    topics: tuple[str, ...] = GENERIC_TOPICS


@dataclass(frozen=True, slots=True)
class Action:
    """What to do next.

    `topic` and `difficulty` are `None` exactly when `move is FINISH`, because a
    terminated interview has nothing to ask. A caller reading them without
    checking gets None rather than a plausible-looking question to generate.
    """

    move: Move
    topic: str | None
    difficulty: QuestionDifficulty | None


def easier(difficulty: QuestionDifficulty) -> QuestionDifficulty:
    """One rung down, clamped at EASY."""
    index = LADDER.index(difficulty)
    return LADDER[max(0, index - 1)]


def harder(difficulty: QuestionDifficulty) -> QuestionDifficulty:
    """One rung up, clamped at EXPERT."""
    index = LADDER.index(difficulty)
    return LADDER[min(len(LADDER) - 1, index + 1)]


def next_topic(state: InterviewState) -> str | None:
    """The first blueprint topic not yet covered, or None if all are.

    In the blueprint's order, not the order they happened to be covered in, so
    two interviews for one role walk the same path -- which is what makes
    comparing them mean anything.
    """
    for topic in state.topics:
        if topic not in state.topics_covered:
            return topic
    return None


def current_topic(state: InterviewState) -> str | None:
    """The topic most recently asked about, or the first one if none yet."""
    if state.topics_covered:
        return state.topics_covered[-1]
    return next_topic(state)


def next_action(state: InterviewState, score: float) -> Action:
    """Given where the interview is and how the last answer scored, what next.

    `score` is the overall for the answer just given, on 0.0-1.0.
    """
    # Budget first, before the score is even read. See the module note: taking
    # ADR-013's table top-down would let a strong final answer buy an extra
    # question, and that bug would only show up for the people doing best.
    if state.questions_asked >= state.question_budget:
        return Action(move=Move.FINISH, topic=None, difficulty=None)

    if score < STRUGGLING_BELOW:
        # Same topic, gentler. They have not shown they understand it yet, and
        # moving on would leave the gap unexamined -- the opposite of what
        # somebody rehearsing wants.
        return Action(
            move=Move.CLARIFY,
            topic=current_topic(state),
            difficulty=easier(state.current_difficulty),
        )

    if score < STRONG_AT_OR_ABOVE:
        # Holding steady: same rung, move along the blueprint. With every topic
        # covered there is nowhere further to go, so stay on the last one --
        # the budget ends the interview, not running out of topics.
        following = next_topic(state)
        return Action(
            move=Move.CONTINUE,
            topic=following if following is not None else current_topic(state),
            difficulty=state.current_difficulty,
        )

    # Strong. ADR-013 offers two moves here -- harder, *or* an uncovered topic.
    # An uncovered topic wins while one exists: breadth before depth, because an
    # interview that drills one topic to EXPERT has measured less about somebody
    # than one that establishes competence across the blueprint.
    following = next_topic(state)
    if following is not None:
        return Action(move=Move.ADVANCE, topic=following, difficulty=state.current_difficulty)
    return Action(
        move=Move.ADVANCE,
        topic=current_topic(state),
        difficulty=harder(state.current_difficulty),
    )
