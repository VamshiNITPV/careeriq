"""Running an optimization analysis (US-6.1, ADR-012).

The load-bearing test in this file is the first one: a suggestion that invents
something must not reach the database. Everything else is about failing in a way
the user can act on.

No test here calls a model. `FakeLLMProvider` answers from a script, so the
suite is offline, deterministic, and can produce a fabricated reply on demand --
which is the only way to check that the validator is actually wired in rather
than merely imported.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.integrations.llm import LLMError, LLMQuotaError
from app.integrations.llm.fake import FakeLLMProvider
from app.models.enums import AnalysisStatus, JobSource, JobStatus
from app.models.job import Job
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.models.resume import Resume, ResumeVersion
from app.models.user import User
from app.services.resume.optimization import run_analysis


@pytest.fixture
async def user_id(db_session: AsyncSession) -> uuid.UUID:
    """A user row, created directly.

    Registering through the API would work and is what the API tests do, but it
    drags in the whole auth stack for a service test that only needs a valid
    foreign key.
    """
    user = User(id=uuid7(), email=f"opt-{uuid7()}@example.com", password_hash="x" * 60)
    db_session.add(user)
    await db_session.flush()
    return user.id


RESUME_TEXT = """
Priya Raman
Senior Backend Engineer

Experience
Zerodha - Senior Backend Engineer (March 2019 - Present)
- Worked on the payments backend, handling 12,000 transactions per day.
- Reduced p99 latency by 35% across the settlement service.

Skills
Python, Django, PostgreSQL, Docker
"""

JOB_TEXT = "We need a backend engineer to own payment systems. Python and Django required."


def reply(*suggestions: dict) -> str:
    return json.dumps({"suggestions": list(suggestions)})


HONEST = {
    "section": "experience",
    "original": "Worked on the payments backend.",
    "suggested": "Built and maintained payment processing services.",
    "rationale": "The job is about payment systems.",
    "grounded_in": ["Worked on the payments backend."],
}

FABRICATED = {
    "section": "experience",
    "original": "Reduced p99 latency by 35% across the settlement service.",
    # 40% is not in the resume. 35% is.
    "suggested": "Reduced p99 latency by 40% across the settlement service.",
    "rationale": "Stronger number.",
    "grounded_in": ["Reduced p99 latency by 35% across the settlement service."],
}


async def an_analysis(
    session: AsyncSession, user_id: uuid.UUID, *, raw_text: str | None = RESUME_TEXT
) -> OptimizationAnalysis:
    resume = Resume(id=uuid7(), user_id=user_id, title="CV")
    session.add(resume)
    await session.flush()

    version = ResumeVersion(
        id=uuid7(),
        resume_id=resume.id,
        version_number=1,
        storage_key=f"test/{uuid7()}",
        original_filename="cv.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        content_hash="0" * 64,
        raw_text=raw_text,
    )
    job = Job(
        id=uuid7(),
        title="Senior Backend Engineer",
        description_raw=JOB_TEXT,
        # Real value rather than a placeholder: it is the near-duplicate key,
        # and two jobs sharing one would collide in a way unrelated to this test.
        content_hash=hashlib.sha256(f"{uuid7()}".encode()).hexdigest(),
        source=JobSource.USER_SUBMITTED,
        status=JobStatus.ACTIVE,
    )
    session.add_all([version, job])
    await session.flush()

    analysis = OptimizationAnalysis(
        id=uuid7(), user_id=user_id, resume_version_id=version.id, job_id=job.id
    )
    session.add(analysis)
    await session.flush()
    return analysis


async def stored(session: AsyncSession, analysis_id: uuid.UUID) -> list[OptimizationSuggestion]:
    rows = await session.scalars(
        select(OptimizationSuggestion)
        .where(OptimizationSuggestion.analysis_id == analysis_id)
        .order_by(OptimizationSuggestion.position)
    )
    return list(rows)


class TestTheValidatorIsWiredIn:
    """ADR-012 step 4. The rest of the feature is worth nothing without this."""

    async def test_a_fabricated_suggestion_never_reaches_the_database(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """The whole point.

        Not stored with a flag, not stored and hidden -- not stored. A row that
        must never be displayed is a row waiting to be displayed by mistake.
        """
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider([reply(FABRICATED)])

        result = await run_analysis(analysis.id, session=db_session, provider=provider)

        assert result.kept == 0
        assert result.rejected_by_validator == 1
        assert await stored(db_session, analysis.id) == []

    async def test_an_honest_suggestion_survives(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """The other half. A validator that rejects everything is not safe, it
        is broken -- and would pass the test above."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider([reply(HONEST)])

        result = await run_analysis(analysis.id, session=db_session, provider=provider)

        rows = await stored(db_session, analysis.id)
        assert result.kept == 1
        assert result.rejected_by_validator == 0
        assert rows[0].suggested == HONEST["suggested"]

    async def test_one_fabrication_does_not_discard_the_honest_ones(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """Each suggestion is judged alone. Dropping the batch would throw away
        good work because the model got one line wrong."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider([reply(HONEST, FABRICATED)])

        result = await run_analysis(analysis.id, session=db_session, provider=provider)

        rows = await stored(db_session, analysis.id)
        assert (result.kept, result.rejected_by_validator) == (1, 1)
        assert [row.suggested for row in rows] == [HONEST["suggested"]]

    async def test_positions_are_contiguous_after_a_rejection(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """Numbering follows what was kept, not what the model sent. Otherwise
        the screen shows "1." then "3." and invites the reader to wonder what
        they are not being told."""
        analysis = await an_analysis(db_session, user_id)
        second = {**HONEST, "original": "Skills", "suggested": "Python, Django, PostgreSQL"}
        provider = FakeLLMProvider([reply(FABRICATED, HONEST, second)])

        await run_analysis(analysis.id, session=db_session, provider=provider)

        assert [row.position for row in await stored(db_session, analysis.id)] == [1, 2]

    async def test_the_rejection_count_is_recorded(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """Without it, a validator silently rejecting everything looks exactly
        like a model that had nothing to say."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider([reply(FABRICATED, FABRICATED)])

        await run_analysis(analysis.id, session=db_session, provider=provider)
        await db_session.refresh(analysis)

        assert analysis.rejected_by_validator == 2
        assert analysis.status is AnalysisStatus.COMPLETE

    async def test_malformed_entries_are_counted_apart_from_fabrications(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """A model inventing facts and a model returning the wrong shape are
        different problems with different fixes. One number would hide which."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider([reply(FABRICATED, {"suggested": "no original field"})])

        await run_analysis(analysis.id, session=db_session, provider=provider)
        await db_session.refresh(analysis)

        assert analysis.rejected_by_validator == 1
        assert analysis.dropped_malformed == 1


class TestWhatItSendsTheModel:
    async def test_the_resume_goes_in_as_untrusted_context(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """A resume is a document a stranger wrote. It belongs between the
        markers, never in instruction position (ADR-014)."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider([reply()])

        await run_analysis(analysis.id, session=db_session, provider=provider)

        sent = provider.calls[0]
        assert "Zerodha" in sent.context["RESUME"]
        assert "Zerodha" not in sent.instruction
        assert "Zerodha" not in sent.system

    async def test_it_records_the_prompt_version_and_the_model(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """"Suggestions got worse last week" is unanswerable without them."""
        analysis = await an_analysis(db_session, user_id)

        await run_analysis(
            analysis.id, session=db_session, provider=FakeLLMProvider([reply()], model="fake-9")
        )
        await db_session.refresh(analysis)

        assert analysis.prompt_version == "resume_optimization@1"
        assert analysis.model == "fake-9"


class TestFailing:
    """Every failure lands on the row in words a user can read. A background
    task has nowhere to raise to, so an exception here is a row stuck at RUNNING
    forever."""

    async def test_a_quota_failure_says_so_and_does_not_invite_a_retry(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """Separated from other failures because the user can act on it. A
        generic "something went wrong" invites an immediate retry that is
        guaranteed to fail identically."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider(error=LLMQuotaError("429", provider="fake"))

        result = await run_analysis(analysis.id, session=db_session, provider=provider)
        await db_session.refresh(analysis)

        assert result.status is AnalysisStatus.FAILED
        assert analysis.status is AnalysisStatus.FAILED
        assert "later" in (analysis.error or "")

    async def test_a_provider_failure_is_recorded_not_raised(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider(error=LLMError("boom", provider="fake"))

        result = await run_analysis(analysis.id, session=db_session, provider=provider)
        await db_session.refresh(analysis)

        assert result.status is AnalysisStatus.FAILED
        assert analysis.error

    async def test_an_unreadable_reply_fails_rather_than_storing_nothing_quietly(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """COMPLETE with no suggestions means "nothing to improve". This is not
        that, and reporting it as that would be a lie the user acts on."""
        analysis = await an_analysis(db_session, user_id)
        provider = FakeLLMProvider(["I'm sorry, I can't help with that."])

        result = await run_analysis(analysis.id, session=db_session, provider=provider)
        await db_session.refresh(analysis)

        assert result.status is AnalysisStatus.FAILED
        assert analysis.status is AnalysisStatus.FAILED

    async def test_a_resume_with_no_text_fails_before_spending_a_call(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """There is nothing to tailor and nothing to validate against, so asking
        would spend quota to get an answer that must be thrown away."""
        analysis = await an_analysis(db_session, user_id, raw_text=None)
        provider = FakeLLMProvider([reply(HONEST)])

        result = await run_analysis(analysis.id, session=db_session, provider=provider)

        assert result.status is AnalysisStatus.FAILED
        assert provider.calls == []

    async def test_no_provider_configured_is_a_readable_failure(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        analysis = await an_analysis(db_session, user_id)

        result = await run_analysis(analysis.id, session=db_session, provider=None)
        await db_session.refresh(analysis)

        assert result.status is AnalysisStatus.FAILED
        assert "not configured" in (analysis.error or "")

    async def test_an_empty_suggestion_list_completes(
        self, db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int
    ) -> None:
        """"I have nothing to suggest" is a valid answer, and the prompt asks
        for it whenever a rewrite would require inventing something."""
        analysis = await an_analysis(db_session, user_id)

        result = await run_analysis(
            analysis.id, session=db_session, provider=FakeLLMProvider([reply()])
        )
        await db_session.refresh(analysis)

        assert result.status is AnalysisStatus.COMPLETE
        assert analysis.error is None
        assert analysis.completed_at is not None

    async def test_a_missing_analysis_is_reported_rather_than_crashing(
        self, db_session: AsyncSession
    ) -> None:
        result = await run_analysis(
            uuid.uuid4(), session=db_session, provider=FakeLLMProvider([reply()])
        )

        assert result.status is AnalysisStatus.FAILED


@pytest.mark.parametrize(
    "bad_suggestion",
    [
        {**HONEST, "suggested": "AWS Certified Solutions Architect on payment systems."},
        {**HONEST, "suggested": "Built payment services at Stripe."},
        {**HONEST, "suggested": "Led the payments backend since 2015."},
        {**HONEST, "suggested": "Deployed payment services on Kubernetes."},
    ],
    ids=["certification", "employer", "date", "skill"],
)
async def test_every_kind_of_invention_is_stopped(
    db_session: AsyncSession, user_id: uuid.UUID, seeded_skills: int, bad_suggestion: dict
) -> None:
    """The validator has its own exhaustive tests; this checks the *wiring*
    holds for each kind rather than only for the numeric case above."""
    analysis = await an_analysis(db_session, user_id)
    provider = FakeLLMProvider([reply(bad_suggestion)])

    result = await run_analysis(analysis.id, session=db_session, provider=provider)

    assert result.kept == 0
    assert await stored(db_session, analysis.id) == []
