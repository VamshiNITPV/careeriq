"""Run one resume-optimization analysis (US-6.1, ADR-012).

The pipeline ADR-012 specifies, in order: extract the job's requirements, ask
for rewrites of the candidate's **existing** content, then **validate every
suggestion programmatically** and keep only what survives.

## The validator is not optional and not advisory

Every suggestion is re-read against the resume before it is stored, and one that
fails is dropped -- not stored with a flag, not shown greyed out. A row that must
never be displayed is a row waiting to be displayed by mistake, and the mistake
costs a user their credibility in an interview.

The count is recorded instead, which is what keeps the behaviour observable. A
validator quietly rejecting everything would otherwise be indistinguishable from
a model with nothing to say.

## Never raises

The caller is a background task with nowhere to propagate to. An unhandled
exception would vanish into the event loop and leave the row stuck at RUNNING
with no explanation, which is the failure mode `ProcessingStatus` was given its
error column to prevent. Every failure lands on the row in words a user can read.

## Why the whole resume is the validation source

Not the bullet being rewritten. A rephrase may legitimately pull a detail from
the summary or the skills block, and validating against the span alone would
reject the candidate for using their own words from two lines up.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.integrations.llm import (
    LLMError,
    LLMProvider,
    LLMQuotaError,
    LLMResponse,
    LLMUnavailableError,
    get_llm_provider,
)
from app.integrations.llm.base import Prompt
from app.integrations.prompts import resume_optimization
from app.integrations.prompts.parsing import ResponseFormatError, parse_suggestions
from app.models.enums import AnalysisStatus
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeVersionRepository
from app.repositories.skill import SkillRepository
from app.services.resume.fabrication import validate_suggestion
from app.services.resume.skill_extraction import build_matcher

log = get_logger(__name__)

#: Longest resume text sent to the model.
#:
#: A generous cap on a document that is normally two pages. Past this something
#: is wrong -- a book pasted into the upload, or an extractor that looped -- and
#: sending it spends quota on a request that will not produce a useful answer.
_MAX_RESUME_CHARS = 20_000
_MAX_JOB_CHARS = 12_000

#: Pause before the single retry on a busy provider.
_RETRY_DELAY_SECONDS = 3


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    status: AnalysisStatus
    kept: int = 0
    rejected_by_validator: int = 0
    dropped_malformed: int = 0
    error: str | None = None


async def run_analysis(
    analysis_id: uuid.UUID,
    *,
    session: AsyncSession | None = None,
    provider: LLMProvider | None = None,
) -> AnalysisResult:
    """Produce suggestions for one analysis row. Never raises.

    `session` and `provider` are injectable for the same reason the resume
    pipeline's are: a test's rows live in an uncommitted transaction a separate
    connection cannot see, and a test must never call a real model.
    """
    if session is not None:
        return await _run(session, analysis_id, provider)

    async with get_session_factory()() as own_session:
        return await _run(own_session, analysis_id, provider)


async def _complete_with_one_retry(
    provider: LLMProvider, prompt: Prompt, analysis_id: uuid.UUID
) -> LLMResponse:
    """One call, and one retry if the provider says it is merely busy.

    The adapter deliberately does not retry, and that stays true for every other
    failure: on a free tier a retry spends a scarce call to re-ask a question
    that just failed. A 503 is the exception the rule does not cover. Google
    marks it temporary in its own words -- "spikes in demand are usually
    temporary" -- and it cleared within seconds when it happened here, so the
    alternative is telling the user to do by hand what one short wait does for
    them.

    Exactly one retry, and only on 503. Two would start to look like a way of
    hammering through a real outage.
    """
    try:
        return await provider.complete(prompt)
    except LLMUnavailableError:
        log.info("optimization: provider busy, retrying once", analysis_id=str(analysis_id))
        await asyncio.sleep(_RETRY_DELAY_SECONDS)
        return await provider.complete(prompt)


async def _fail(
    session: AsyncSession, analysis: OptimizationAnalysis, reason: str
) -> AnalysisResult:
    analysis.status = AnalysisStatus.FAILED
    analysis.error = reason
    analysis.completed_at = datetime.now(UTC)
    await session.commit()
    return AnalysisResult(status=AnalysisStatus.FAILED, error=reason)


async def _run(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    provider: LLMProvider | None,
) -> AnalysisResult:
    analysis = await session.get(OptimizationAnalysis, analysis_id)
    if analysis is None:
        # Nothing to record the failure on. Logged and dropped, like the resume
        # pipeline does for a missing version.
        log.error("optimization: analysis not found", analysis_id=str(analysis_id))
        return AnalysisResult(status=AnalysisStatus.FAILED, error="analysis not found")

    provider = provider or get_llm_provider()
    if provider is None:
        return await _fail(
            session,
            analysis,
            "AI suggestions are not configured on this server.",
        )

    version = await ResumeVersionRepository(session).get(analysis.resume_version_id)
    if version is None or not (version.raw_text or "").strip():
        return await _fail(
            session,
            analysis,
            "We couldn't read any text from this resume version, so there is "
            "nothing to tailor.",
        )

    job = await JobRepository(session).get(analysis.job_id)
    if job is None:
        return await _fail(session, analysis, "That job is no longer available.")

    resume_text = version.raw_text[:_MAX_RESUME_CHARS]  # type: ignore[index]
    prompt = resume_optimization.build(
        resume_text=resume_text,
        job_title=job.title,
        job_description=(job.description_raw or "")[:_MAX_JOB_CHARS],
    )

    analysis.status = AnalysisStatus.RUNNING
    analysis.prompt_version = f"{prompt.name}@{prompt.version}"
    await session.commit()

    try:
        response = await _complete_with_one_retry(provider, prompt, analysis_id)
    except LLMUnavailableError:
        return await _fail(
            session,
            analysis,
            "The AI service is busy right now. This usually clears within a "
            "minute -- please try again.",
        )
    except LLMQuotaError:
        # Separated from any other failure because the user can act on it: wait
        # and try again. "Something went wrong" would invite a retry that is
        # guaranteed to fail the same way.
        return await _fail(
            session,
            analysis,
            "We've hit today's limit for AI suggestions. Please try again later.",
        )
    except LLMError as exc:
        log.warning("optimization: provider failed", analysis_id=str(analysis_id), error=str(exc))
        return await _fail(
            session, analysis, "The AI service couldn't complete this request. Please try again."
        )

    analysis.model = response.model
    analysis.prompt_tokens = response.prompt_tokens
    analysis.completion_tokens = response.completion_tokens

    try:
        parsed = parse_suggestions(response.text)
    except ResponseFormatError as exc:
        # The model answered, but not in a usable shape. Logged with the reason
        # because this is a defect in the prompt or the model rather than
        # something the user did, and the prompt version is on the row.
        log.warning(
            "optimization: unusable reply",
            analysis_id=str(analysis_id),
            prompt_version=analysis.prompt_version,
            reason=str(exc),
        )
        return await _fail(
            session, analysis, "The AI service returned something we couldn't read."
        )

    matcher = build_matcher(await SkillRepository(session).load_taxonomy())

    kept = 0
    rejected = 0
    for raw in parsed.suggestions:
        result = validate_suggestion(
            suggested=raw.suggested,
            # The whole resume, not the span being rewritten.
            source=resume_text,
            matcher=matcher,
        )
        if not result.passed:
            rejected += 1
            log.info(
                "optimization: suggestion rejected",
                analysis_id=str(analysis_id),
                entities=[f"{e.kind}:{e.text}" for e in result.fabricated],
            )
            continue

        kept += 1
        session.add(
            OptimizationSuggestion(
                id=uuid7(),
                analysis_id=analysis.id,
                position=kept,
                section=raw.section,
                original=raw.original,
                suggested=raw.suggested,
                rationale=raw.rationale,
                grounded_in=list(raw.grounded_in),
                # Kept even though it passed: a claim about safety with no
                # evidence behind it cannot be checked later.
                validation={"passed": True, "fabricated_entities": []},
            )
        )

    analysis.status = AnalysisStatus.COMPLETE
    analysis.rejected_by_validator = rejected
    analysis.dropped_malformed = parsed.dropped
    analysis.completed_at = datetime.now(UTC)
    await session.commit()

    log.info(
        "optimization: complete",
        analysis_id=str(analysis_id),
        kept=kept,
        rejected_by_validator=rejected,
        dropped_malformed=parsed.dropped,
    )
    return AnalysisResult(
        status=AnalysisStatus.COMPLETE,
        kept=kept,
        rejected_by_validator=rejected,
        dropped_malformed=parsed.dropped,
    )
