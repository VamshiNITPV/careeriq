"""The interview-scoring dataset, and the guard that keeps its labels honest.

## The digest

Human scores are expensive -- five judgements each over a hundred answers -- and
that expense creates a specific temptation: when the answers change, reuse the
scores. `content_digest()` hashes every question and answer, the scores file
records the digest they were made against, and `load_human_scores()` refuses to
load when the two disagree.

The failure it prevents is quiet. Nothing crashes when a score meant for one
answer is attached to a different one; the metrics simply report a worse
agreement, and the obvious reading of that is "the model got worse". A week can
go into chasing a regression that is really a mislabelled row. So the check is
not a nicety -- it is the difference between a number that means something and a
number that looks like it does.

Editing an answer therefore invalidates the scores for the whole file, which is
deliberate friction. The right move after an edit is to rescore, not to widen
the check.

## Partial scoring is allowed, and counted

Scoring a hundred answers is a sitting or two, so a file with sixty scored
answers loads and the runner reports the count. What is not allowed is a score
that is incomplete in *shape* -- four of the five dimensions, or a value outside
the scale -- because that is a mistake rather than progress, and averaging over
whichever dimensions survived would produce a figure that reads as a full mark.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass

from datasets.interview_scoring.answers import ANSWERS
from datasets.interview_scoring.cases import (
    PROFILES,
    QUESTIONS,
    QUESTIONS_BY_ID,
    Answer,
    Question,
)

__all__ = [
    "ANSWERS",
    "ANSWERS_BY_ID",
    "DIMENSIONS",
    "PROFILES",
    "QUESTIONS",
    "QUESTIONS_BY_ID",
    "Answer",
    "HumanScores",
    "Question",
    "ScoresStale",
    "content_digest",
    "load_human_scores",
    "scores_path",
]

#: The five dimensions, in the order the scorer reports them.
#:
#: Duplicated from `app.services.interview.scoring` rather than imported,
#: because this package must be readable without the backend on the path -- the
#: review sheet is generated from it and that should not need a running app.
#: `run_scoring_eval.py` asserts the two lists are identical, so the duplication
#: cannot drift silently.
DIMENSIONS: tuple[str, ...] = (
    "technical",
    "relevance",
    "completeness",
    "communication",
    "structure",
)

ANSWERS_BY_ID: dict[str, Answer] = {a.id: a for a in ANSWERS}

_HERE = pathlib.Path(__file__).parent


def scores_path() -> pathlib.Path:
    """Where the human's marks live once they exist."""
    return _HERE / "human_scores.json"


class ScoresStale(RuntimeError):
    """The scores were made against different answers. Carries both digests."""


def content_digest() -> str:
    """A hash over every question and answer in the set.

    Covers the question text and its rubric as well as the answers, because
    `completeness` is marked against the rubric -- changing `expected_points`
    changes what a correct mark is, even with the answer untouched.

    Built from a canonical JSON dump rather than from the repr of the objects:
    a repr is not a stable format across Python versions, and a digest that
    changes when nothing did would train everybody to pass `--force`.
    """
    payload = {
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "expected_points": list(q.expected_points),
                "target_role": q.target_role,
                "topic": q.topic,
                "difficulty": q.difficulty,
            }
            for q in sorted(QUESTIONS, key=lambda q: q.id)
        ],
        "answers": [
            {"id": a.id, "question_id": a.question_id, "text": a.text}
            for a in sorted(ANSWERS, key=lambda a: a.id)
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HumanScores:
    """One person's marks over some or all of the set."""

    digest: str
    scored_by: str
    #: answer id -> dimension -> mark in [0, 1]
    marks: dict[str, dict[str, float]]

    @property
    def count(self) -> int:
        return len(self.marks)

    def overall(self, answer_id: str) -> float:
        """The mean of the five, computed the same way the model's is.

        Computed here rather than asked of the human for the reason the scorer
        does not ask the model: two authoritative overalls can disagree, and
        comparing a human's holistic impression against a computed mean would
        measure the difference between those two things as though it were
        disagreement about the answer.
        """
        marks = self.marks[answer_id]
        return sum(marks[name] for name in DIMENSIONS) / len(DIMENSIONS)


def load_human_scores(path: pathlib.Path | None = None) -> HumanScores:
    """Read the marks, refusing anything that does not describe *these* answers.

    Raises `FileNotFoundError` if nobody has scored yet, `ScoresStale` if the
    answers have changed since, and `ValueError` for a malformed mark.
    """
    source = path or scores_path()
    payload = json.loads(source.read_text(encoding="utf-8"))

    recorded = payload.get("digest", "")
    current = content_digest()
    if recorded != current:
        raise ScoresStale(
            f"scored against {recorded or '(none recorded)'}, answers are now {current}. "
            "The questions or answers changed after these marks were given, so the marks "
            "no longer describe them. Regenerate the review sheet and rescore."
        )

    raw = payload.get("scores")
    if not isinstance(raw, dict):
        raise ValueError("'scores' missing or not an object")

    marks: dict[str, dict[str, float]] = {}
    for answer_id, values in raw.items():
        if answer_id not in ANSWERS_BY_ID:
            raise ValueError(f"{answer_id!r} is not an answer in this set")
        if not isinstance(values, dict):
            raise ValueError(f"{answer_id}: expected an object of five marks")
        row: dict[str, float] = {}
        for name in DIMENSIONS:
            value = values.get(name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{answer_id}: {name} is missing or not a number")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{answer_id}: {name} is {value}, outside 0..1")
            row[name] = float(value)
        marks[answer_id] = row

    return HumanScores(
        digest=recorded,
        scored_by=str(payload.get("scored_by", "unrecorded")),
        marks=marks,
    )
