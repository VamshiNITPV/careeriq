"""Turning accepted suggestions into a new version (US-6.1 AC3).

Tested at the service level rather than through HTTP, because the properties
that matter here cannot be observed through a request. The session dependency
rolls back on any exception -- correct in production, where each request owns
its session -- and in the test harness that discards the rows the test created,
so "nothing was written" and "everything was written and then undone" look
identical from outside.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

import pdfplumber
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.integrations.storage import LocalObjectStorage
from app.models.enums import AnalysisStatus, SuggestionDecision
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.models.resume import Resume, ResumeVersion
from app.models.user import User
from app.services.resume.apply_suggestions import NothingToApplyError, apply_accepted

RESUME_TEXT = """Priya Raman
Senior Backend Engineer

Experience
- Worked on the payments backend.
- Reduced p99 latency by 35%.
"""


@pytest.fixture
async def user_id(db_session: AsyncSession) -> uuid.UUID:
    user = User(id=uuid7(), email=f"apply-{uuid7()}@example.com", password_hash="x" * 60)
    db_session.add(user)
    await db_session.flush()
    return user.id


async def a_setup(
    session: AsyncSession, user_id: uuid.UUID, *, suggestions: int = 2
) -> tuple[OptimizationAnalysis, ResumeVersion, list[OptimizationSuggestion]]:
    resume = Resume(id=uuid7(), user_id=user_id, title="CV")
    session.add(resume)
    await session.flush()

    version = ResumeVersion(
        id=uuid7(),
        resume_id=resume.id,
        version_number=1,
        storage_key=f"test/{uuid7()}",
        original_filename="priya.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        content_hash=hashlib.sha256(RESUME_TEXT.encode()).hexdigest(),
        raw_text=RESUME_TEXT,
    )
    session.add(version)
    await session.flush()

    from app.models.enums import JobSource, JobStatus
    from app.models.job import Job

    job = Job(
        id=uuid7(),
        title="Backend Engineer",
        description_raw="Payments.",
        content_hash=hashlib.sha256(f"{uuid7()}".encode()).hexdigest(),
        source=JobSource.USER_SUBMITTED,
        status=JobStatus.ACTIVE,
    )
    session.add(job)
    await session.flush()

    analysis = OptimizationAnalysis(
        id=uuid7(),
        user_id=user_id,
        resume_version_id=version.id,
        job_id=job.id,
        status=AnalysisStatus.COMPLETE,
    )
    session.add(analysis)
    await session.flush()

    originals = ["Worked on the payments backend.", "Reduced p99 latency by 35%."]
    rewrites = ["Built and maintained payment services.", "Cut p99 latency by 35%."]
    rows = []
    for index in range(suggestions):
        row = OptimizationSuggestion(
            id=uuid7(),
            analysis_id=analysis.id,
            position=index + 1,
            section="experience",
            original=originals[index],
            suggested=rewrites[index],
            rationale="Relevant to the job.",
            grounded_in=[originals[index]],
            validation={"passed": True, "fabricated_entities": []},
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return analysis, version, rows


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStorage:
    return LocalObjectStorage(tmp_path / "objects")


class TestNothingIsWrittenUnlessEverythingCan:
    async def test_a_failed_apply_leaves_every_decision_untouched(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """The reason the service decides in full before it writes.

        An earlier version marked each suggestion as it went and raised at the
        end, leaving the caller to undo it. That makes correctness depend on
        every caller remembering to roll back -- and "the write already happened,
        please ignore it" is a worse contract than never having written.
        """
        analysis, version, rows = await a_setup(db_session, user_id)

        with pytest.raises(NothingToApplyError):
            await apply_accepted(
                db_session,
                analysis=analysis,
                source=version,
                accepted_ids=set(),
                storage=store,
            )

        for row in rows:
            assert row.decision is SuggestionDecision.PENDING
            assert row.decided_at is None

    async def test_a_failed_apply_writes_no_version(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """A version identical to its parent is clutter with a number on it, and
        implies a change the user cannot find."""
        analysis, version, _ = await a_setup(db_session, user_id)

        with pytest.raises(NothingToApplyError):
            await apply_accepted(
                db_session,
                analysis=analysis,
                source=version,
                accepted_ids=set(),
                storage=store,
            )

        from sqlalchemy import func, select

        count = await db_session.scalar(
            select(func.count())
            .select_from(ResumeVersion)
            .where(ResumeVersion.resume_id == version.resume_id)
        )
        assert count == 1

    async def test_an_accepted_suggestion_that_no_longer_matches_is_not_applied(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """Replacement is exact, never fuzzy. If the wording has moved on, the
        safe answer is to skip rather than guess where it belongs."""
        analysis, version, rows = await a_setup(db_session, user_id)
        rows[0].original = "Text that is not in this resume."
        await db_session.flush()

        with pytest.raises(NothingToApplyError):
            await apply_accepted(
                db_session,
                analysis=analysis,
                source=version,
                accepted_ids={rows[0].id},
                storage=store,
            )


class TestASuccessfulApply:
    async def test_it_stores_a_pdf_whose_text_matches_the_version(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """The stored file has to say what the version says.

        A version whose file disagrees with its own text hands someone the
        untailored document while the screen shows the tailored words. Checked
        by extracting the PDF rather than comparing bytes, because the file is
        now a rendering of the text rather than the text itself -- and the
        extraction is also what an applicant tracking system does.
        """
        analysis, version, rows = await a_setup(db_session, user_id)

        result = await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id},
            storage=store,
        )

        blob = await store.get(result.version.storage_key)
        assert blob.startswith(b"%PDF-")
        assert result.version.mime_type == "application/pdf"
        assert result.version.original_filename.endswith("-tailored.pdf")

        with pdfplumber.open(io.BytesIO(blob)) as document:
            joined = chr(10)
            extracted = joined.join(
                page.extract_text() or "" for page in document.pages
            )
        assert rows[0].suggested in " ".join(extracted.split())

    async def test_an_accepted_suggestion_that_did_not_land_is_counted(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """The user chose it. A count that quietly differs from what they picked
        is the kind of thing that destroys trust in the feature."""
        analysis, version, rows = await a_setup(db_session, user_id)
        rows[1].original = "Not present anywhere."
        await db_session.flush()

        result = await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id, rows[1].id},
            storage=store,
        )

        assert result.applied == 1
        assert result.not_found == 1
        # Still accepted: recording a rejection would misrepresent the decision.
        assert rows[1].decision is SuggestionDecision.ACCEPTED
        assert rows[1].applied_version_id is None

    async def test_it_does_not_make_the_tailored_version_current(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """`resumes.current_version_id` is what the matcher, the skill extractor
        and the embeddings read.

        A tailored version is wording the user proposed for one job, not a new
        statement of who they are, so pointing the profile at it would quietly
        re-base every match on text written for a single application. Only the
        upload service and the parse pipeline set it, and this pins that
        `apply_accepted` stays out of that business.
        """
        analysis, version, rows = await a_setup(db_session, user_id)
        resume = await db_session.get(Resume, version.resume_id)
        await db_session.refresh(resume)  # type: ignore[arg-type]
        before = resume.current_version_id  # type: ignore[union-attr]

        result = await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id},
            storage=store,
        )

        await db_session.refresh(resume)  # type: ignore[arg-type]
        assert resume.current_version_id == before  # type: ignore[union-attr]
        assert resume.current_version_id != result.version.id  # type: ignore[union-attr]

    async def test_it_edits_the_original_pdf_when_it_can(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """The layout path, not the fallback.

        Without this the fallback could quietly win every time and the feature
        would look like it worked while producing a plain document every run.
        """
        from app.services.resume.pdf import build_resume_pdf

        analysis, version, rows = await a_setup(db_session, user_id)
        # A real PDF behind the source version, which is what the editor needs.
        await store.put(
            version.storage_key, build_resume_pdf(RESUME_TEXT), content_type="application/pdf"
        )

        result = await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id},
            storage=store,
        )

        assert result.kept_layout is True
        blob = await store.get(result.version.storage_key)
        with pdfplumber.open(io.BytesIO(blob)) as document:
            extracted = " ".join(
                " ".join((page.extract_text() or "").split()) for page in document.pages
            )
        assert rows[0].suggested in extracted
        assert rows[0].original not in extracted

    async def test_it_falls_back_when_the_source_is_not_a_pdf(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """A clean document is a better answer than no document. The user still
        gets their wording; what they lose is the layout, and `kept_layout`
        says so rather than leaving them to notice."""
        analysis, version, rows = await a_setup(db_session, user_id)
        version.mime_type = "text/plain"
        await db_session.flush()

        result = await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id},
            storage=store,
        )

        assert result.kept_layout is False
        assert (await store.get(result.version.storage_key)).startswith(b"%PDF-")

    async def test_the_tailored_version_is_marked_generated(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        """What keeps it out of "the newest thing the user gave us".

        Three separate things read that: which version the page opens, which
        status the list reports, and which version Re-extract re-parses. The
        last would derive profile skills from wording written for one job.
        """
        analysis, version, rows = await a_setup(db_session, user_id)

        result = await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id},
            storage=store,
        )

        assert result.version.is_generated is True
        assert version.is_generated is False

    async def test_the_source_version_keeps_its_own_text(
        self,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        store: LocalObjectStorage,
    ) -> None:
        analysis, version, rows = await a_setup(db_session, user_id)

        await apply_accepted(
            db_session,
            analysis=analysis,
            source=version,
            accepted_ids={rows[0].id},
            storage=store,
        )

        assert version.raw_text == RESUME_TEXT
        assert version.mime_type == "application/pdf"
