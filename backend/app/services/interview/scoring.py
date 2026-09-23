"""Scoring one answer on five dimensions (US-8.3).

`ml.md` section 7.1 names the dimensions and where the rubric comes from: the
question's own `expected_points`, fixed when the question was written and before
any answer existed. That ordering is what makes this a mark against stated
criteria rather than against an impression -- a model asked "was this good?"
will answer, and the answer will not mean anything twice running.

## The overall score is computed, not asked for

The model returns five numbers. The sixth is arithmetic over them, done here.

Asking for it would produce two authoritative values that can disagree, and the
disagreement would be invisible: a model that returns `0.9` alongside five
dimensions averaging `0.4` is not reporting a weighting, it is reporting
nothing. Equal weights, because `ml.md` names the five without ranking them --
and inventing a ranking here would be a claim about what matters in an interview
that nothing in this project has measured.

## Citations are offsets, and offsets are checked

US-8.3 AC2 wants feedback that cites the specific part of the answer it refers
to, and `ml.md` section 6.1 requires "cited spans must be valid offsets". So the
model returns `[start, end)` into the answer, and every span is verified to lie
inside it. A span that does not is dropped.

Offsets rather than quoted text for the same reason `grounded_in` is anchored
rather than trusted: a quote is a copy the model can paraphrase without anybody
noticing, where an offset either lands on the candidate's own words or is out of
range and detectably wrong. When the model *also* supplies the quote, it is
checked against what actually sits at those offsets, and a mismatch drops the
span -- a citation pointing somewhere other than where it says is worse than no
citation, because it will be believed.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal

from app.core.logging import get_logger
from app.integrations.llm.base import LLMProvider, LLMUnavailableError, Prompt
from app.integrations.prompts.parsing import unfence
from app.services.interview.prompts import scoring_prompt

log = get_logger(__name__)

#: The five, in the order `ml.md` section 7.1 lists them.
DIMENSIONS: tuple[str, ...] = (
    "technical",
    "relevance",
    "completeness",
    "communication",
    "structure",
)

_RETRY_DELAY_SECONDS = 2.0
_MAX_FEEDBACK = 4_000
_MAX_POINT = 400
_MAX_POINTS = 6
_MAX_SPANS = 8


class ScoreRejected(ValueError):
    """The reply was not a usable score. Carries why, for the log."""


@dataclass(frozen=True, slots=True)
class CitedSpan:
    """A range of the answer the feedback refers to, verified to be in it."""

    start: int
    end: int
    #: What sits at those offsets, taken from the answer rather than the model.
    text: str
    #: Why the feedback points here.
    note: str


@dataclass(frozen=True, slots=True)
class AnswerScore:
    """One answer, marked."""

    dimensions: dict[str, Decimal]
    overall: Decimal
    feedback: str
    strengths: tuple[str, ...]
    improvements: tuple[str, ...]
    cited_spans: tuple[CitedSpan, ...]
    model: str = ""


def _fraction(value: object) -> Decimal | None:
    """A number in [0, 1] as a 3-place Decimal, or None.

    Bounds are checked rather than clamped. A model returning 4.5 has not
    produced a high score, it has misread the scale -- and clamping would turn a
    parsing failure into a perfect mark, which is the worst available reading.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not 0.0 <= float(value) <= 1.0:
        return None
    return Decimal(str(round(float(value), 3)))


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


def _points(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        point for raw in value[:_MAX_POINTS] if (point := _text(raw, _MAX_POINT))
    )


def _spans(value: object, answer: str) -> tuple[CitedSpan, ...]:
    """Spans that genuinely lie inside the answer. Others are dropped.

    Dropped rather than rejecting the whole score: the marks are still usable
    when one citation is malformed, and losing four good ones because the fifth
    had a bad offset would be a worse answer, not a safer one. The same
    reasoning `prompts/parsing.py` gives for keeping partial results.
    """
    if not isinstance(value, list):
        return ()

    found: list[CitedSpan] = []
    for raw in value[:_MAX_SPANS]:
        if not isinstance(raw, dict):
            continue
        start, end = raw.get("start"), raw.get("end")
        # `bool` is an `int` in Python, so `True` would pass an isinstance
        # check and index the answer at 1. Excluded explicitly.
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not 0 <= start < end <= len(answer)
        ):
            continue

        actual = answer[start:end]
        claimed = raw.get("text")
        # A citation pointing somewhere other than where it says is worse than
        # no citation, because it will be believed. Whitespace is forgiven;
        # words are not. Only checked when the model supplied a quote -- the
        # offsets alone are already verified above.
        if (
            isinstance(claimed, str)
            and claimed.strip()
            and claimed.strip().split() != actual.strip().split()
        ):
            log.info("interview: citation offsets did not match its quote")
            continue

        note = _text(raw.get("note"), _MAX_POINT) or ""
        found.append(CitedSpan(start=start, end=end, text=actual, note=note))

    return tuple(found)


def parse_score(reply: str, *, answer: str) -> AnswerScore:
    """Read a scoring reply strictly. Pure -- no model, no database.

    Raises `ScoreRejected` with the reason. The caller decides about retrying.
    """
    try:
        payload = json.loads(unfence(reply))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ScoreRejected("reply was not JSON") from exc

    if not isinstance(payload, dict):
        raise ScoreRejected("reply was not a JSON object")

    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, dict):
        raise ScoreRejected("scores missing or not an object")

    dimensions: dict[str, Decimal] = {}
    for name in DIMENSIONS:
        value = _fraction(raw_scores.get(name))
        if value is None:
            # Every dimension, or none. A partial score would be averaged over
            # the ones that survived and read as a complete mark -- US-8.3 AC1
            # asks for five, and four of five is a different measurement wearing
            # the same name.
            raise ScoreRejected(f"score for {name!r} missing or outside 0..1")
        dimensions[name] = value

    feedback = _text(payload.get("feedback"), _MAX_FEEDBACK)
    if feedback is None:
        raise ScoreRejected("feedback missing or empty")

    overall = Decimal(
        str(round(sum(float(v) for v in dimensions.values()) / len(DIMENSIONS), 3))
    )

    return AnswerScore(
        dimensions=dimensions,
        overall=overall,
        feedback=feedback,
        strengths=_points(payload.get("strengths")),
        improvements=_points(payload.get("improvements")),
        cited_spans=_spans(payload.get("cited_spans"), answer),
    )


async def score_answer(
    provider: LLMProvider,
    *,
    question_text: str,
    expected_points: list[str],
    answer_text: str,
    target_role: str,
) -> AnswerScore:
    """Mark one answer against the question's own rubric.

    Two attempts. A score is a number that will be shown as fact and fed to the
    adaptive policy, so an unusable reply is reported rather than guessed at --
    there is no sensible default for "how good was this", and 0.5 would be a
    fabrication with a confident face.
    """
    prompt: Prompt = scoring_prompt(
        question_text=question_text,
        expected_points=expected_points,
        answer_text=answer_text,
        target_role=target_role,
    )

    last = "no attempt succeeded"
    for attempt in (1, 2):
        try:
            try:
                reply = (await provider.complete(prompt)).text
            except LLMUnavailableError:
                # One retry on a 503 only, the reasoning `optimization.py`
                # records: Google calls it temporary, and every other failure
                # spends a scarce free-tier call re-asking a failed question.
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                reply = (await provider.complete(prompt)).text
            score = parse_score(reply, answer=answer_text)
        except ScoreRejected as exc:
            last = str(exc)
            log.info("interview: score rejected", attempt=attempt, reason=last)
            continue

        return AnswerScore(
            dimensions=score.dimensions,
            overall=score.overall,
            feedback=score.feedback,
            strengths=score.strengths,
            improvements=score.improvements,
            cited_spans=score.cited_spans,
            model=provider.model,
        )

    raise ScoreRejected(last)
