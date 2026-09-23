"""Seed the deployed demo (deployment).

    docker compose -f docker-compose.prod.yml run --rm backend python -m app.data.demo

Idempotent, and re-run nightly on the VM. The demo account is shared, so
whatever a visitor changes is put back rather than left for the next person.

## Why a fixture rather than a live app

An empty app is not a demo. Somebody who opens this has no resume to upload and
no reason to trust it enough to paste one, so what they see has to already be
there: a profile, a corpus, real match scores, skill gaps, and applications
spread across the funnel.

## What is and is not real here

The jobs and their embeddings are **real** — exported from a working database by
`export_demo.py`, model output for the text they accompany. The match scores
shown on the jobs and match screens are therefore genuinely computed rather than
written down.

**One exception, added with US-7.2 and labelled where it lives.** The
`match_score_at_apply` snapshots in `DEMO_SCORES` are invented. They are a
record of what a past score *was*, for applications an invented person never
sent, and nothing recomputes them — so there is no way to derive them and no
way for a reader to check them. Spreading them across the bands is what makes
the score-band table show a distribution rather than one row.

The person is invented. "Asha Mehra" is not anybody, the resume text was written
for this file, and the account exists to be logged into by strangers. That is
stated rather than implied, because a demo that quietly ships a real person's
resume is a very different thing to publish.

## The resume's vector is also real, and is not optional

An earlier version of this file assumed a missing resume embedding would only
cost the semantic *dimension* of each match. It does not: stage-one recall
returns nothing without it, so match-sorted browse comes back empty with
`availability: PENDING` — the headline feature blank. Found by seeding a demo
without one and looking.

So `export_demo.py` embeds `RESUME_TEXT` with the same model as the jobs, in the
embedder container, and the vector ships alongside them. Same model on both
sides is what makes the scores comparable at all; a vector from a different one
would be arithmetic on unrelated numbers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.application import Application, ApplicationEvent
from app.models.embedding import CandidateEmbedding, JobEmbedding
from app.models.enums import (
    ApplicationEventType,
    ApplicationStatus,
    EducationLevel,
    ExperienceLevel,
    JobSource,
    JobStatus,
    ProcessingStatus,
    SkillRequirement,
    WorkMode,
)
from app.models.job import Job, JobSkill
from app.models.profile import Profile
from app.models.resume import Resume, ResumeVersion
from app.models.skill import CandidateSkill, Skill
from app.models.user import User
from app.services.resume.pipeline import seed_skill_taxonomy

log = get_logger(__name__)

FIXTURE = pathlib.Path(__file__).parent / "demo_jobs.json"
RESUME_VECTOR = pathlib.Path(__file__).parent / "demo_resume_vector.json"

#: What produced the fixture's vectors. Recorded on every row, so a later model
#: change is a detectable mismatch rather than a silent one.
EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"
EMBEDDING_MODEL_VERSION = "1"

DEMO_EMAIL = "demo@careeriq.app"
#: Published in the README. S105 flags any constant that looks like a
#: credential, and it is right to — but this one is meant to be known. Hiding a
#: published password in an env var would make the demo harder to open without
#: making anything safer.
DEMO_PASSWORD = "CareerIQDemo2026!"  # noqa: S105

RESUME_TEXT = """Asha Mehra
Backend Engineer

Summary
Backend engineer with four years building payment and settlement services.

Experience
Zerodha - Backend Engineer (March 2022 - Present)
- Worked on the payments backend, handling 12,000 transactions per day.
- Reduced p99 latency by 35% across the settlement service.
- Migrated the ledger from MySQL to PostgreSQL with no downtime.
- Mentored three junior engineers.

Freshworks - Software Engineer (June 2020 - February 2022)
- Built REST APIs for the billing platform in Python and Django.
- Automated a manual reconciliation process that took two days each week.

Skills
Python, Django, PostgreSQL, Redis, Docker, Git, REST APIs

Education
B.Tech in Computer Science, NIT Warangal, 2020
"""

#: Skills the demo profile claims. Names, resolved against the seeded taxonomy.
PROFILE_SKILLS = ("Python", "Django", "PostgreSQL", "Redis", "Docker", "Git")

#: Where she says she wants to go, which is what skill gaps are measured
#: against. Substring-matched against job titles by `_target_job_ids`, so these
#: are chosen to actually hit the fixture: 5, 2 and 3 postings respectively.
#:
#: Note they do *not* describe her current job. That is the point. A backend
#: engineer moving toward AI work has real gaps, so the demo shows the feature
#: doing something; targeting "Backend Engineer" would produce a congratulatory
#: empty list that demonstrates nothing (and matches no posting in this corpus
#: anyway, which would be NO_JOBS rather than a gap report).
TARGET_ROLES = ("AI Engineer", "Machine Learning Engineer", "Data Engineer")

#: Match scores recorded against the seeded applications (US-7.2 AC2).
#:
#: Written rather than computed, and the distinction matters. Everything else
#: in this file that looks like a model output *is* one -- the vectors are real,
#: which is the whole reason `export_demo.py` exists. These are not: they are
#: plausible numbers chosen to spread across the score bands so the demo shows
#: the feature instead of one bar and four empty rows.
#:
#: That is a fabrication, so it is labelled one. It is acceptable here only
#: because the alternative is a table nobody can tell works, and because the
#: number is a *snapshot of a past score* -- a historical claim about a moment
#: that never happened for an invented person, not a live computation anyone
#: could check against this corpus.
DEMO_SCORES = ("72.40", "64.10", "58.75", "61.20", "47.90", "55.30")

#: One application per stage, so the funnel has something in every column and
#: the lifecycle is visible rather than described.
FUNNEL_SPREAD = (
    ApplicationStatus.SAVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.ASSESSMENT,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
)


async def _wipe(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Remove what a visitor may have changed, leaving the corpus alone.

    Applications, skills and the resume belong to the demo account and are
    rebuilt. Jobs are shared market data that nothing in the UI can edit, so
    re-inserting them every night would churn 40 rows and every embedding for no
    reason.

    Candidate skills have to be removed explicitly. They are keyed on
    `(user_id, skill_id)` and outlive the resume that produced them — deleting a
    version only nulls their `source_version_id`. The second run of this seed
    hit that unique constraint, which is the nightly reset failing on night two.
    """
    for row in await session.scalars(
        select(Application).where(Application.user_id == user_id)
    ):
        await session.delete(row)
    for row in await session.scalars(
        select(CandidateSkill).where(CandidateSkill.user_id == user_id)
    ):
        await session.delete(row)
    for row in await session.scalars(select(Resume).where(Resume.user_id == user_id)):
        await session.delete(row)
    await session.flush()


async def _jobs(session: AsyncSession) -> list[Job]:
    """Load the fixture, inserting anything not already present."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    skills = {row.name: row.id for row in await session.scalars(select(Skill))}
    out: list[Job] = []

    for entry in payload:
        # The posting text is the identity. Re-running must not duplicate a
        # corpus, and the content hash is what the app already dedupes on.
        digest = hashlib.sha256(entry["description_raw"].encode()).hexdigest()
        existing = await session.scalar(select(Job).where(Job.content_hash == digest))
        if existing is not None:
            out.append(existing)
            continue

        job = Job(
            id=uuid7(),
            title=entry["title"],
            description_raw=entry["description_raw"],
            content_hash=digest,
            location=entry["location"],
            country_code=entry["country_code"],
            source=JobSource.DATASET_IMPORT,
            status=JobStatus.ACTIVE,
            posted_at=datetime.now(UTC) - timedelta(days=len(out) % 20),
        )
        session.add(job)
        await session.flush()

        for link in entry["skills"]:
            skill_id = skills.get(link["name"])
            if skill_id is not None:
                session.add(
                    JobSkill(
                        job_id=job.id,
                        skill_id=skill_id,
                        requirement=SkillRequirement(link["requirement"]),
                    )
                )

        session.add(
            JobEmbedding(
                id=uuid7(),
                job_id=job.id,
                embedding=entry["embedding"],
                model_name=EMBEDDING_MODEL,
                model_version=EMBEDDING_MODEL_VERSION,
                # Both are NOT NULL, and both are load-bearing rather than
                # bookkeeping: the dimension is what lets a model change be
                # detected instead of corrupting rows, and the source hash is
                # how the indexer knows a posting has not been re-embedded for
                # text it no longer has.
                dimensions=len(entry["embedding"]),
                source_text_hash=digest,
            )
        )
        out.append(job)

    await session.flush()
    return out


async def seed_demo(session: AsyncSession) -> dict[str, int]:
    """Build the demo account. Safe to run repeatedly."""
    await seed_skill_taxonomy(session)

    user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            id=uuid7(),
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()

    # Upserted rather than wiped: `profiles.user_id` is UNIQUE, and a second
    # insert on the nightly re-run would fail on the constraint.
    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        profile = Profile(id=uuid7(), user_id=user.id)
        session.add(profile)
    profile.full_name = "Asha Mehra"
    profile.headline = "Backend Engineer moving into AI engineering"
    profile.location = "Bengaluru, India"
    profile.country_code = "IN"
    profile.years_of_experience = Decimal("4.0")
    profile.current_experience_level = ExperienceLevel.MID
    profile.highest_education = EducationLevel.BACHELORS
    # Without these, /api/v1/skills/gaps answers NO_TARGET and the screen is
    # blank — correctly, since nothing has been measured. Found by seeding a
    # demo without them and reading the response rather than the code.
    profile.target_roles = list(TARGET_ROLES)
    profile.preferred_work_modes = [WorkMode.REMOTE, WorkMode.HYBRID]
    await session.flush()

    await _wipe(session, user.id)
    jobs = await _jobs(session)

    resume = Resume(id=uuid7(), user_id=user.id, title="Asha Mehra - Backend Engineer")
    session.add(resume)
    await session.flush()

    body = RESUME_TEXT.encode()
    version = ResumeVersion(
        id=uuid7(),
        resume_id=resume.id,
        version_number=1,
        # No file is written. Nothing in the demo downloads it, and storing a
        # fabricated PDF would put a document in a bucket that nobody authored.
        storage_key=f"demo/{uuid7()}.txt",
        original_filename="asha-mehra.txt",
        mime_type="text/plain",
        file_size_bytes=len(body),
        content_hash=hashlib.sha256(body).hexdigest(),
        raw_text=RESUME_TEXT,
        processing_status=ProcessingStatus.COMPLETE,
        processed_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    resume.current_version_id = version.id

    # Without these the skill-gap and match screens have nothing to compare
    # against, and the demo shows empty states for the two features it most
    # needs to demonstrate.
    vector = json.loads(RESUME_VECTOR.read_text(encoding="utf-8"))
    session.add(
        CandidateEmbedding(
            id=uuid7(),
            # Keyed to the version, not the user: a match records which resume
            # produced it, and a vector that could not be traced to one would
            # make that unanswerable.
            resume_version_id=version.id,
            embedding=vector,
            model_name=EMBEDDING_MODEL,
            model_version=EMBEDDING_MODEL_VERSION,
            dimensions=len(vector),
            source_text_hash=hashlib.sha256(RESUME_TEXT.encode()).hexdigest(),
        )
    )

    named = {row.name: row.id for row in await session.scalars(select(Skill))}
    for name in PROFILE_SKILLS:
        skill_id = named.get(name)
        if skill_id is not None:
            session.add(
                CandidateSkill(
                    id=uuid7(),
                    user_id=user.id,
                    skill_id=skill_id,
                    source_version_id=version.id,
                )
            )
    await session.flush()

    now = datetime.now(UTC)
    for index, status in enumerate(FUNNEL_SPREAD):
        if index >= len(jobs):
            break
        applied_at = None if status is ApplicationStatus.SAVED else now - timedelta(days=index + 3)
        application = Application(
            id=uuid7(),
            user_id=user.id,
            job_id=jobs[index].id,
            status=status,
            is_saved=index % 2 == 0,
            applied_at=applied_at,
            # The snapshot, on applications that were actually sent. A SAVED row
            # gets neither, matching what the API does -- seeding one would put
            # a score in the band table for a job nothing was sent to, which is
            # exactly the bug the API is tested against.
            resume_version_id=None if applied_at is None else version.id,
            match_score_at_apply=(
                None if applied_at is None else Decimal(DEMO_SCORES[index % len(DEMO_SCORES)])
            ),
        )
        session.add(application)
        await session.flush()

        # The log is what US-7.2's funnel reads, and an application with a
        # status but no history would show a stage it never passed through.
        session.add(
            ApplicationEvent(
                id=uuid7(),
                application_id=application.id,
                from_status=None,
                to_status=ApplicationStatus.SAVED,
                event_type=ApplicationEventType.STATUS_CHANGE,
                occurred_at=now - timedelta(days=index + 5),
            )
        )
        if status is not ApplicationStatus.SAVED:
            session.add(
                ApplicationEvent(
                    id=uuid7(),
                    application_id=application.id,
                    from_status=ApplicationStatus.SAVED,
                    to_status=status,
                    event_type=ApplicationEventType.STATUS_CHANGE,
                    occurred_at=applied_at,
                )
            )

    await session.commit()
    return {"jobs": len(jobs), "applications": min(len(FUNNEL_SPREAD), len(jobs))}


async def main() -> None:
    async with get_session_factory()() as session:
        counts = await seed_demo(session)
    log.info("demo seeded", email=DEMO_EMAIL, **counts)


if __name__ == "__main__":
    asyncio.run(main())
