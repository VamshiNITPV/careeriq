"""Generating one interview question, and refusing the ones that are wrong.

ADR-013 gives the model a narrow job: write the *text* of a question for a
`(topic, difficulty)` the policy chose. Everything below is about checking it
did that, because a question is only worth asking if it is about what was asked
for and about somebody who actually exists.

## Four gates

1. **It parses.** A reply that is not the schema produces nothing. Not a partial
   object with plausible defaults -- `integrations/prompts/parsing.py` already
   makes that argument and it holds here.

2. **The topic and difficulty are the ones requested.** `ml.md:609` requires it
   in those words. A model that quietly substitutes an easier topic leaves the
   adaptive policy driving something that ignores it, and every score after that
   measures a different interview from the one the trajectory describes.

3. **`grounded_in` anchors in the resume.** This is the fabrication guard. If
   the model says it built on "migrated the ledger from MySQL to PostgreSQL",
   those words must actually be in the resume -- checked with
   `resume/anchoring.py`'s matcher, which is whitespace-tolerant and word-exact
   because extracted PDF text wraps and models do not copy cleanly. A
   `grounded_in` that does not anchor is a claim about the candidate they never
   made, and the question goes.

4. **An entity check, deliberately soft.** See below.

## Gate 4 is credentials only, and that is a retreat I measured into

It began as the full entity check `resume/fabrication.py` runs, softened to a
retry-then-degrade rather than a rejection. Two runs against the real model
showed that was still far too broad: the "fabrications" it found were `RAG`,
`BM25`, `WSGI`, `ASGI` and `GIL`. Those are the field's vocabulary. A question
about Python concurrency is *supposed* to say `GIL`, and a check that calls it
an invention makes its own fallback the normal path -- which is the same failure
as having no gate, with more machinery.

The deeper problem is that the check cannot tell **attribution** from
**hypothesis**, and that distinction is the entire question. "At Netflix you
handled failover" and "how would you handle failover at scale" contain the same
kinds of entity; only the first is a claim about the candidate. Nothing at the
entity level separates them, and every threshold I could pick either waves
through real fabrications or rejects ordinary questions.

So it now flags one thing: **an invented credential**. "Your AWS certification",
"your PMP" -- the canonical fabrication ADR-012 was written for, almost never
legitimate vocabulary inside a question, and detectable by the credential words
the validator already recognises.

What carries the rest of the load is gate 3, which is deterministic and does not
have this problem: a claim about the candidate must quote the candidate. The
prompt forbids attribution in as many words besides.

A failure here means: try once more with a blunter instruction, then fall back
to a question grounded only in the topic. **Degraded, never fabricated**, and
the degradation is stored on the row -- `interview_questions.degraded` -- so a
report can say the personalisation did not hold rather than quietly pretending
it did.

There is no fallback question bank. US-8.1 AC1 rules one out by name, and a bank
that appears only when the model fails is still a bank.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.integrations.llm.base import (
    LLMProvider,
    LLMUnavailableError,
    Prompt,
)
from app.integrations.prompts.parsing import unfence
from app.models.enums import QuestionDifficulty
from app.services.interview.prompts import question_prompt
from app.services.resume.anchoring import find_span
from app.services.resume.fabrication import EntityKind, validate_suggestion
from app.services.resume.skill_extraction import SkillMatcher

log = get_logger(__name__)

#: One retry, only on a 503, matching `resume/optimization.py`'s reasoning:
#: Google calls it temporary in its own words, and every other failure spends a
#: scarce free-tier call re-asking a question that just failed.
_RETRY_DELAY_SECONDS = 2.0

#: Caps, so one bad reply cannot put an unbounded string in a column.
_MAX_QUESTION = 1_000
_MAX_POINT = 400
_MAX_POINTS = 8


class QuestionRejected(ValueError):
    """The reply was not a usable question. Carries why, for the log."""


@dataclass(frozen=True, slots=True)
class GeneratedQuestion:
    """A question that passed every gate."""

    question_text: str
    topic: str
    difficulty: QuestionDifficulty
    expected_points: tuple[str, ...]
    #: The resume words it builds on, verified to be there. None if it builds on
    #: nothing specific, which is allowed.
    grounded_in: str | None
    #: True when gate 4 rejected the personalised attempts and this is the
    #: topic-only fallback. Surfaced, not swallowed.
    degraded: bool = False
    model: str = ""
    fabricated: tuple[str, ...] = field(default_factory=tuple)


def _text(value: object, limit: int) -> str | None:
    """A non-empty string within length, or None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


def parse_question(
    reply: str,
    *,
    topic: str,
    difficulty: QuestionDifficulty,
    resume_text: str,
) -> GeneratedQuestion:
    """Gates 1 to 3. Pure -- no model, no database, no network.

    Raises `QuestionRejected` with the reason. The caller decides whether to
    retry; this only decides whether the reply is usable.
    """
    try:
        payload = json.loads(unfence(reply))
    except (json.JSONDecodeError, ValueError) as exc:
        raise QuestionRejected("reply was not JSON") from exc

    if not isinstance(payload, dict):
        raise QuestionRejected("reply was not a JSON object")

    question_text = _text(payload.get("question_text"), _MAX_QUESTION)
    if question_text is None:
        raise QuestionRejected("question_text missing, empty or too long")

    # Gate 2. Compared case-insensitively on the stripped value, because a model
    # that returns the right topic in different case has obeyed; one that
    # returns a different topic has not, and that is the distinction worth
    # making rather than punishing capitalisation.
    returned_topic = _text(payload.get("topic"), _MAX_QUESTION)
    if returned_topic is None or returned_topic.casefold() != topic.strip().casefold():
        raise QuestionRejected(
            f"topic drifted: asked for {topic!r}, got {returned_topic!r}"
        )

    returned_difficulty = _text(payload.get("difficulty"), 32)
    if (
        returned_difficulty is None
        or returned_difficulty.strip().upper() != difficulty.value
    ):
        raise QuestionRejected(
            f"difficulty drifted: asked for {difficulty.value}, got {returned_difficulty!r}"
        )

    raw_points = payload.get("expected_points")
    if not isinstance(raw_points, list) or not raw_points:
        raise QuestionRejected("expected_points missing or empty")
    points = tuple(
        point for value in raw_points[:_MAX_POINTS] if (point := _text(value, _MAX_POINT))
    )
    if not points:
        # The rubric is what 9.3 scores against. Without it every score
        # downstream is the model marking against its own impression, which is
        # exactly what ml.md section 7.1 says this must not be.
        raise QuestionRejected("expected_points had no usable entries")

    # Gate 3. `null` is a legitimate answer -- a question need not build on
    # anything specific -- but a non-null one is a claim, and a claim gets
    # checked.
    grounded_in = payload.get("grounded_in")
    anchored: str | None = None
    if grounded_in is not None:
        anchored = _text(grounded_in, _MAX_QUESTION)
        if anchored is None:
            raise QuestionRejected("grounded_in present but not usable text")
        if find_span(resume_text, anchored) is None:
            raise QuestionRejected(
                "grounded_in is not in the resume: " + anchored[:120]
            )

    return GeneratedQuestion(
        question_text=question_text,
        topic=topic,
        difficulty=difficulty,
        expected_points=points,
        grounded_in=anchored,
    )


#: Where a sentence starts, for the opener rule below. Mirrors the validator's
#: own notion of a sentence break rather than inventing a second one.
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+|\n\s*)$")


def _only_ever_sentence_initial(token: str, text: str) -> bool:
    """True when every occurrence of `token` sits where any word is capitalised.

    The validator's opener list is tuned for resume prose -- "Led", "Built",
    "Improved". Questions open with "Walk", "Describe", "Given", "Suppose", and
    it reads each of those as an invented organisation. A gate that fires on
    nearly every question carries no signal at all, and its fallback becomes the
    normal path.

    So rather than widening the shared list -- which would weaken it for the
    resume feature, where over-rejection is the *correct* bias -- this caller
    drops tokens that only ever appear where capitalisation is forced. An
    acronym is never dropped: "AWS Certified" opening a sentence is the
    canonical fabrication and the validator is right to catch it.
    """
    if len(token) > 1 and token.isupper():
        return False
    for match in re.finditer(rf"\b{re.escape(token)}\b", text):
        if not _SENTENCE_START.search(text[: match.start()]):
            return False
    return True


def check_entities(
    question: GeneratedQuestion,
    *,
    resume_text: str,
    posting_text: str | None,
    matcher: SkillMatcher | None = None,
) -> tuple[str, ...]:
    """Gate 4. Entities in the question that appear in neither source.

    Returns what it found rather than a pass/fail, because the caller's response
    is graded -- retry, then degrade -- not binary. See the module note on why
    this is advisory here and absolute in the resume feature.
    """
    source = resume_text if not posting_text else f"{resume_text}\n\n{posting_text}"
    result = validate_suggestion(
        suggested=question.question_text, source=source, matcher=matcher
    )
    return tuple(
        entity.text
        for entity in result.fabricated
        if entity.kind is EntityKind.CREDENTIAL
        # Still dropped even when credential-shaped: questions open with
        # "Describe" and "Given", and a sentence-initial capital is capitalised
        # because it has to be, not because it names anything.
        and not _only_ever_sentence_initial(entity.text, question.question_text)
    )


async def _complete_once(provider: LLMProvider, prompt: Prompt) -> str:
    """One call, retried once if the provider says it is merely busy."""
    try:
        return (await provider.complete(prompt)).text
    except LLMUnavailableError:
        log.info("interview: provider busy, retrying once", prompt=prompt.name)
        await asyncio.sleep(_RETRY_DELAY_SECONDS)
        return (await provider.complete(prompt)).text


async def generate_question(
    provider: LLMProvider,
    *,
    topic: str,
    difficulty: QuestionDifficulty,
    target_role: str,
    resume_text: str,
    posting_text: str | None = None,
    matcher: SkillMatcher | None = None,
) -> GeneratedQuestion:
    """One question, gated. Raises `QuestionRejected` if none survives.

    Two attempts at a personalised question, then one at a topic-only question.
    The last is marked `degraded` rather than presented as equivalent.
    """
    prompt = question_prompt(
        topic=topic,
        difficulty=difficulty,
        target_role=target_role,
        resume_text=resume_text,
        posting_text=posting_text,
    )

    last_reason = "no attempt succeeded"
    for attempt in (1, 2):
        try:
            reply = await _complete_once(provider, prompt)
            question = parse_question(
                reply, topic=topic, difficulty=difficulty, resume_text=resume_text
            )
        except QuestionRejected as exc:
            last_reason = str(exc)
            log.info("interview: question rejected", attempt=attempt, reason=last_reason)
            continue

        fabricated = check_entities(
            question, resume_text=resume_text, posting_text=posting_text, matcher=matcher
        )
        if not fabricated:
            return GeneratedQuestion(
                question_text=question.question_text,
                topic=question.topic,
                difficulty=question.difficulty,
                expected_points=question.expected_points,
                grounded_in=question.grounded_in,
                model=provider.model,
            )

        last_reason = "unsupported entities: " + ", ".join(fabricated[:5])
        log.info("interview: entities unsupported", attempt=attempt, found=list(fabricated))

    # Both personalised attempts failed a gate. Ask for the same topic with no
    # resume to build on: a weaker question, and an honest one.
    bare = question_prompt(
        topic=topic,
        difficulty=difficulty,
        target_role=target_role,
        # Not the real resume. The point of this attempt is to remove the
        # material the model kept over-reaching from; leaving it in would invite
        # the same failure a third time.
        resume_text="(not provided for this question)",
        posting_text=posting_text,
    )
    try:
        reply = await _complete_once(provider, bare)
        question = parse_question(
            reply,
            topic=topic,
            difficulty=difficulty,
            # Nothing can anchor against an absent resume, so a `grounded_in`
            # here must be null -- and an empty source makes `find_span` say so.
            resume_text="",
        )
    except QuestionRejected as exc:
        raise QuestionRejected(f"{last_reason}; fallback also failed: {exc}") from exc

    log.info("interview: falling back to an ungrounded question", reason=last_reason)
    return GeneratedQuestion(
        question_text=question.question_text,
        topic=question.topic,
        difficulty=question.difficulty,
        expected_points=question.expected_points,
        grounded_in=None,
        degraded=True,
        model=provider.model,
    )
