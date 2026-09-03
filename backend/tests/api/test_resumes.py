"""API tests for resume upload, parsing, and skill management."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProcessingStatus
from app.models.resume import Resume, ResumeVersion
from app.models.skill import CandidateSkill
from app.services.file_validation import MAX_UPLOAD_BYTES
from tests.fixtures.documents import build_docx, build_image_only_pdf, build_pdf

API = "/api/v1"


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def pdf_upload(name: str = "resume.pdf") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, build_pdf(), "application/pdf")}


class TestUpload:
    async def test_accepts_a_pdf_and_returns_202(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "PENDING"
        assert body["is_duplicate"] is False
        assert body["poll_url"].endswith("/status")

    async def test_accepts_a_docx(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        files = {
            "file": (
                "resume.docx",
                build_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=files)
        assert response.status_code == 202

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/resumes", files=pdf_upload())
        assert response.status_code == 401

    async def test_rejects_a_non_document(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Named .pdf, but the bytes say otherwise (ADR-014)."""
        files = {"file": ("resume.pdf", b"not a pdf at all" * 20, "application/pdf")}
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=files)

        assert response.status_code == 415
        assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    async def test_rejects_an_oversized_file(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        oversized = b"%PDF-1.4" + b"\x00" * (MAX_UPLOAD_BYTES + 1)
        files = {"file": ("big.pdf", oversized, "application/pdf")}
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=files)

        assert response.status_code == 413

    async def test_validation_happens_before_acceptance(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        # A rejected file must leave no rows behind: failing after accepting
        # would leave an orphan resume that never parses (US-2.1 AC4).
        files = {"file": ("resume.pdf", b"junk" * 100, "application/pdf")}
        await client.post(f"{API}/resumes", headers=auth_headers, files=files)

        assert len(list((await db_session.scalars(select(Resume))).all())) == 0

    async def test_stores_under_a_generated_key_not_the_filename(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        """Path traversal is structurally impossible, not filtered."""
        await client.post(
            f"{API}/resumes", headers=auth_headers, files=pdf_upload("../../etc/passwd.pdf")
        )

        version = await db_session.scalar(select(ResumeVersion))
        assert version is not None
        assert ".." not in version.storage_key
        assert "passwd" not in version.storage_key
        assert version.storage_key.startswith("resumes/")
        # The original name survives as display metadata only.
        assert version.original_filename == "passwd.pdf"

    async def test_first_resume_becomes_primary(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())

        resume = await db_session.scalar(select(Resume))
        assert resume is not None
        assert resume.is_primary is True

    async def test_identical_file_reuses_the_previous_parse(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # The SAME bytes both times. build_pdf() must not be called twice here:
        # a PDF embeds a creation timestamp, so two generated files differ and
        # hash differently — which is exactly what deduplication is designed to
        # notice, and would make this test silently prove nothing.
        identical = build_pdf()
        upload = {"file": ("resume.pdf", identical, "application/pdf")}

        first = await client.post(f"{API}/resumes", headers=auth_headers, files=upload)
        parsed = await run_pipeline(uuid.UUID(first.json()["version_id"]))
        # Assert the precondition explicitly: if the first parse did not
        # complete, the duplicate check below is testing nothing.
        assert parsed.status is ProcessingStatus.COMPLETE, parsed.error

        second = await client.post(f"{API}/resumes", headers=auth_headers, files=upload)

        # Reprocessing identical bytes can only produce the result we already
        # have, so the pipeline is skipped.
        assert second.json()["is_duplicate"] is True
        assert second.json()["status"] == "COMPLETE"


class TestOwnership:
    async def test_another_users_resume_returns_404_not_403(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """403 would confirm the id exists and allow enumeration (US-1.5 AC1)."""
        owner = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        resume_id = owner.json()["resume_id"]

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "intruder@example.com", "password": "correct-horse-9"},
        )
        intruder_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.get(f"{API}/resumes/{resume_id}", headers=intruder_headers)
        assert response.status_code == 404

    async def test_cannot_download_another_users_file(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        owner = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = owner.json()["version_id"]

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "intruder2@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.get(
            f"{API}/resumes/versions/{version_id}/download", headers=headers
        )
        assert response.status_code == 404

    async def test_unknown_id_returns_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(f"{API}/resumes/{uuid.uuid4()}", headers=auth_headers)
        assert response.status_code == 404


class TestPipeline:
    async def test_parses_a_resume_end_to_end(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = uuid.UUID(response.json()["version_id"])

        result = await run_pipeline(version_id)

        assert result.status is ProcessingStatus.COMPLETE
        assert result.characters_extracted > 500
        assert result.sections_detected >= 4
        assert result.skills_written > 5

    async def test_writes_candidate_skills_with_provenance(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = uuid.UUID(response.json()["version_id"])
        await run_pipeline(version_id)

        rows = list((await db_session.scalars(select(CandidateSkill))).all())
        assert len(rows) > 5
        # Provenance: a user asking why a skill is on their profile must get an
        # answer better than "the parser decided".
        assert all(r.source_version_id == version_id for r in rows)
        assert all(r.extraction_confidence is not None for r in rows)
        assert all(r.is_user_verified is False for r in rows)

    async def test_resolves_aliases_to_canonical_skills(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # The fixture resume says "Postgres" and "K8s".
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        listed = await client.get(f"{API}/profile/skills", headers=auth_headers)
        names = {row["skill"]["name"] for row in listed.json()}

        assert "PostgreSQL" in names
        assert "Kubernetes" in names

    async def test_reparsing_does_not_duplicate_skills(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """Idempotency (ADR-009).

        A retried or redelivered task must not double a user's skill list.
        """
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = uuid.UUID(response.json()["version_id"])

        await run_pipeline(version_id)
        first_count = len(list((await db_session.scalars(select(CandidateSkill))).all()))

        # Force a genuine re-run rather than the already-complete short circuit.
        version = await db_session.get(ResumeVersion, version_id)
        assert version is not None
        version.processing_status = ProcessingStatus.PENDING
        await db_session.commit()

        await run_pipeline(version_id)
        second_count = len(list((await db_session.scalars(select(CandidateSkill))).all()))

        assert first_count == second_count

    async def test_reparsing_never_overwrites_a_user_correction(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """US-2.4 AC2 — the rule that makes background re-processing safe.

        Without it, re-parsing silently reverts every manual fix the user made,
        which is worse than not re-parsing at all.
        """
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = uuid.UUID(response.json()["version_id"])
        await run_pipeline(version_id)

        listed = await client.get(f"{API}/profile/skills", headers=auth_headers)
        target = listed.json()[0]

        await client.patch(
            f"{API}/profile/skills/{target['id']}",
            headers=auth_headers,
            json={"proficiency": "EXPERT", "years_of_experience": "7.0"},
        )

        version = await db_session.get(ResumeVersion, version_id)
        assert version is not None
        version.processing_status = ProcessingStatus.PENDING
        await db_session.commit()
        await run_pipeline(version_id)

        corrected = await db_session.get(CandidateSkill, uuid.UUID(target["id"]))
        assert corrected is not None
        assert corrected.is_user_verified is True
        assert corrected.proficiency is not None
        assert corrected.proficiency.value == "EXPERT"

    async def test_image_only_pdf_fails_with_a_specific_reason(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # A terminal failure must say why (US-2.2 AC2), or the user has no idea
        # whether to retry or upload something different.
        files = {"file": ("scan.pdf", build_image_only_pdf(), "application/pdf")}
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=files)
        version_id = uuid.UUID(response.json()["version_id"])

        result = await run_pipeline(version_id)
        assert result.status is ProcessingStatus.FAILED

        version = await db_session.get(ResumeVersion, version_id)
        assert version is not None
        assert version.processing_error is not None
        assert "scan" in version.processing_error.lower()


class TestFailedParseIsVisibleInTheList:
    """A failed parse must be distinguishable from a healthy resume.

    The pipeline sets current_version_id only on success, so without the
    latest_version_* fields a resume whose parse failed looks exactly like one
    with no versions at all — and the client has nothing to retry against.
    """

    async def test_list_exposes_the_failure_while_current_stays_null(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        files = {"file": ("scan.pdf", build_image_only_pdf(), "application/pdf")}
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=files)
        version_id = response.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        listed = (await client.get(f"{API}/resumes", headers=auth_headers)).json()
        row = listed[0]

        # No successful parse, so nothing is "current" — that is the whole
        # reason the latest_* fields exist.
        assert row["current_version_id"] is None
        assert row["latest_version_id"] == version_id
        assert row["latest_version_status"] == "FAILED"
        assert row["latest_version_error"] is not None

    async def test_latest_is_the_highest_version_number(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # Ordered by version_number, not created_at: two uploads in the same
        # millisecond would make a timestamp ordering non-deterministic.
        first = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        resume_id = first.json()["resume_id"]
        await run_pipeline(uuid.UUID(first.json()["version_id"]))

        second = await client.post(
            f"{API}/resumes",
            headers=auth_headers,
            files={"file": ("v2.docx", build_docx(), DOCX_MIME)},
            data={"resume_id": resume_id},
        )
        second_version_id = second.json()["version_id"]

        listed = (await client.get(f"{API}/resumes", headers=auth_headers)).json()
        assert listed[0]["latest_version_id"] == second_version_id
        # The first parse succeeded, so current still points at version 1 while
        # version 2 is queued. The two fields mean different things.
        assert listed[0]["current_version_id"] == first.json()["version_id"]
        assert listed[0]["latest_version_status"] == "PENDING"

    async def test_a_resume_with_no_failure_reports_complete(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        row = (await client.get(f"{API}/resumes", headers=auth_headers)).json()[0]
        assert row["latest_version_status"] == "COMPLETE"
        assert row["latest_version_error"] is None
        assert row["latest_version_id"] == row["current_version_id"]

    async def test_detail_reports_the_same_facts_as_the_list(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # Detail derives these from the already-loaded versions relationship
        # rather than a second query, so it cannot contradict the list.
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        resume_id = response.json()["resume_id"]
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        listed = (await client.get(f"{API}/resumes", headers=auth_headers)).json()[0]
        detail = (await client.get(f"{API}/resumes/{resume_id}", headers=auth_headers)).json()

        for field in ("latest_version_id", "latest_version_status", "skill_count"):
            assert detail[field] == listed[field], field
        # skill_count used to be hardcoded to zero on this endpoint while the
        # list computed it; the delete dialog reads that number.
        assert detail["skill_count"] > 0


class TestReparse:
    async def test_reparses_a_failed_version(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # The recovery path for a failed parse. Previously the endpoint had no
        # coverage at all.
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = response.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        version = await db_session.get(ResumeVersion, uuid.UUID(version_id))
        assert version is not None
        version.processing_status = ProcessingStatus.FAILED
        version.processing_error = "something went wrong"
        await db_session.commit()

        again = await client.post(
            f"{API}/resumes/versions/{version_id}/reparse", headers=auth_headers
        )
        assert again.status_code == 202
        assert again.json()["status"] == "PENDING"

        await db_session.refresh(version)
        assert version.processing_error is None

    async def test_refuses_while_already_processing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """Two runs on one version interleave their status commits.

        The visible symptom is a progress bar rewinding from "Finding sections"
        back to "Reading the document" while both runs upsert skills at once.
        """
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = response.json()["version_id"]

        version = await db_session.get(ResumeVersion, uuid.UUID(version_id))
        assert version is not None
        version.processing_status = ProcessingStatus.EXTRACTING
        await db_session.commit()

        conflict = await client.post(
            f"{API}/resumes/versions/{version_id}/reparse", headers=auth_headers
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "ALREADY_PROCESSING"

    async def test_unknown_version_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            f"{API}/resumes/versions/{uuid.uuid4()}/reparse", headers=auth_headers
        )
        assert response.status_code == 404


class TestStatusPolling:
    async def test_reports_progress(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = response.json()["version_id"]

        pending = await client.get(
            f"{API}/resumes/versions/{version_id}/status", headers=auth_headers
        )
        assert pending.json()["status"] == "PENDING"
        assert pending.json()["is_terminal"] is False

        await run_pipeline(uuid.UUID(version_id))

        done = await client.get(f"{API}/resumes/versions/{version_id}/status", headers=auth_headers)
        assert done.json()["status"] == "COMPLETE"
        assert done.json()["percent"] == 100
        assert done.json()["is_terminal"] is True


class TestDownload:
    async def test_returns_the_original_bytes(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        original = build_pdf()
        files = {"file": ("resume.pdf", original, "application/pdf")}
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=files)

        response = await client.get(
            f"{API}/resumes/versions/{upload.json()['version_id']}/download",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.content == original
        assert response.headers["x-content-type-options"] == "nosniff"


class TestResumeManagement:
    async def test_lists_only_your_own(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "someone@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        assert len((await client.get(f"{API}/resumes", headers=auth_headers)).json()) == 1
        assert len((await client.get(f"{API}/resumes", headers=headers)).json()) == 0

    async def test_rename(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        resume_id = upload.json()["resume_id"]

        response = await client.patch(
            f"{API}/resumes/{resume_id}", headers=auth_headers, json={"title": "Backend CV"}
        )
        assert response.json()["title"] == "Backend CV"

    async def test_only_one_resume_can_be_primary(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Enforced by a partial unique index, so this cannot drift even if the
        # service forgets to clear the old primary first.
        first = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        second = await client.post(
            f"{API}/resumes", headers=auth_headers, files={"file": ("b.docx", build_docx(), "x")}
        )

        await client.patch(
            f"{API}/resumes/{second.json()['resume_id']}",
            headers=auth_headers,
            json={"is_primary": True},
        )

        listed = (await client.get(f"{API}/resumes", headers=auth_headers)).json()
        primaries = [r for r in listed if r["is_primary"]]
        assert len(primaries) == 1
        assert primaries[0]["id"] == second.json()["resume_id"]
        assert primaries[0]["id"] != first.json()["resume_id"]

    async def test_delete_is_soft_and_hides_the_resume(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        resume_id = upload.json()["resume_id"]

        await client.delete(f"{API}/resumes/{resume_id}", headers=auth_headers)

        assert (await client.get(f"{API}/resumes", headers=auth_headers)).json() == []
        # The row survives, because applications reference the version they were
        # submitted with (database.md section 3.7).
        row = await db_session.get(Resume, uuid.UUID(resume_id))
        assert row is not None
        assert row.deleted_at is not None


class TestDeleteRemovesExtractedSkills:
    """Deleting a resume must not leave its skills behind.

    Reported as "after deleting the resume the extracted skills are still
    there" — a deleted document leaving untraceable claims on the profile.
    """

    async def test_extracted_skills_go_with_the_resume(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(upload.json()["version_id"]))

        before = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert len(before) > 5

        await client.delete(f"{API}/resumes/{upload.json()['resume_id']}", headers=auth_headers)

        after = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert after == []

    async def test_a_corrected_skill_still_goes_with_its_resume(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """Provenance decides, not verification.

        An earlier version kept verified rows on the reasoning that confirming a
        skill made it the user's own claim. That produced the reported surprise:
        delete the resume, and skills reviewed alongside it stayed behind with
        nothing to trace them to. Correcting an extracted skill does not change
        where it came from.
        """
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(upload.json()["version_id"]))

        listed = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        await client.patch(
            f"{API}/profile/skills/{listed[0]['id']}",
            headers=auth_headers,
            json={"proficiency": "EXPERT"},
        )

        await client.delete(f"{API}/resumes/{upload.json()['resume_id']}", headers=auth_headers)

        assert (await client.get(f"{API}/profile/skills", headers=auth_headers)).json() == []

    async def test_an_accepted_suggestion_goes_with_its_resume(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The exact case reported.

        Suggestions are accepted while reviewing a resume, so they are derived
        from it. Leaving them behind is what made a deleted resume look like it
        had resurrected its skills.
        """
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = upload.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        suggestions = (
            await client.get(
                f"{API}/resumes/versions/{version_id}/suggestions", headers=auth_headers
            )
        ).json()["suggestions"]
        assert suggestions

        accepted = await client.post(
            f"{API}/profile/skills",
            headers=auth_headers,
            json={
                "skill_id": suggestions[0]["skill_id"],
                "source_version_id": version_id,
            },
        )
        assert accepted.status_code == 201

        await client.delete(f"{API}/resumes/{upload.json()['resume_id']}", headers=auth_headers)

        assert (await client.get(f"{API}/profile/skills", headers=auth_headers)).json() == []

    async def test_hand_typed_skills_are_untouched(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """A skill typed in by hand was never about any particular document."""
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(upload.json()["version_id"]))

        await client.post(f"{API}/profile/skills", headers=auth_headers, json={"skill_name": "Bun"})

        await client.delete(f"{API}/resumes/{upload.json()['resume_id']}", headers=auth_headers)

        remaining = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert [s["skill"]["name"] for s in remaining] == ["Bun"]

    async def test_the_list_reports_how_many_skills_a_resume_owns(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # Drives the delete confirmation, so the user is told what they lose.
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(upload.json()["version_id"]))

        listed = (await client.get(f"{API}/resumes", headers=auth_headers)).json()
        assert listed[0]["skill_count"] > 5

    async def test_deleting_one_resume_leaves_another_alone(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        first = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(first.json()["version_id"]))

        second = await client.post(
            f"{API}/resumes",
            headers=auth_headers,
            files={"file": ("other.docx", build_docx(), "application/vnd.ms-word")},
        )
        await run_pipeline(uuid.UUID(second.json()["version_id"]))

        await client.delete(f"{API}/resumes/{first.json()['resume_id']}", headers=auth_headers)

        # The second resume's skills were re-sourced to it by its own parse, so
        # they must remain.
        remaining = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert len(remaining) > 5


class TestSuggestions:
    async def test_accepted_suggestions_stop_being_offered(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """Reported as suggestions reappearing after refresh.

        Suggestions are computed once at parse time and stored, so whether one
        is still worth showing has to be decided against the live profile — not
        against the snapshot taken when the file was parsed.
        """
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = upload.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        first = (
            await client.get(
                f"{API}/resumes/versions/{version_id}/suggestions", headers=auth_headers
            )
        ).json()["suggestions"]
        assert first, "fixture resume should produce at least one suggestion"

        target = first[0]
        added = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": target["skill_id"]}
        )
        assert added.status_code == 201

        second = (
            await client.get(
                f"{API}/resumes/versions/{version_id}/suggestions", headers=auth_headers
            )
        ).json()["suggestions"]

        assert target["name"] not in {s["name"] for s in second}
        assert len(second) == len(first) - 1

    async def test_every_suggestion_carries_evidence(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = upload.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        body = (
            await client.get(
                f"{API}/resumes/versions/{version_id}/suggestions", headers=auth_headers
            )
        ).json()

        for suggestion in body["suggestions"]:
            assert suggestion["evidence"].strip()
            # Never auto-accepted: below the pipeline's write threshold.
            assert float(suggestion["confidence"]) < 0.60


class TestAddSkillByName:
    async def test_creates_a_skill_the_taxonomy_does_not_know(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """No taxonomy is complete.

        Refusing a skill because we have not heard of it leaves the user unable
        to record something true about themselves.
        """
        response = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_name": "Bun"}
        )

        assert response.status_code == 201
        assert response.json()["skill"]["name"] == "Bun"
        assert response.json()["is_user_verified"] is True

    async def test_a_known_name_attaches_to_the_existing_skill(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Typing a name that already exists must not create a duplicate entry
        # that nothing else in the system will ever match.
        response = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_name": "Python"}
        )

        assert response.status_code == 201
        assert response.json()["skill"]["name"] == "Python"

    async def test_an_alias_resolves_to_its_canonical_skill(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_name": "postgres"}
        )

        assert response.status_code == 201
        assert response.json()["skill"]["name"] == "PostgreSQL"

    async def test_rejects_both_identifiers_at_once(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        found = await client.get(f"{API}/skills/search?q=python", headers=auth_headers)
        response = await client.post(
            f"{API}/profile/skills",
            headers=auth_headers,
            json={"skill_id": found.json()[0]["id"], "skill_name": "Python"},
        )
        assert response.status_code == 422

    async def test_rejects_neither_identifier(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(f"{API}/profile/skills", headers=auth_headers, json={})
        assert response.status_code == 422

    async def test_cannot_add_the_same_name_twice(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await client.post(f"{API}/profile/skills", headers=auth_headers, json={"skill_name": "Bun"})
        again = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_name": "bun"}
        )
        assert again.status_code == 409


class TestSkillSearch:
    async def test_finds_by_canonical_name(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.get(f"{API}/skills/search?q=postgres", headers=auth_headers)
        names = {s["name"] for s in response.json()}
        assert "PostgreSQL" in names

    async def test_finds_by_alias(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Typing "k8s" must find Kubernetes, or the taxonomy's alias resolution
        # is invisible to someone adding a skill by hand.
        response = await client.get(f"{API}/skills/search?q=k8s", headers=auth_headers)
        assert "Kubernetes" in {s["name"] for s in response.json()}

    async def test_prefix_matches_rank_first(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.get(f"{API}/skills/search?q=java", headers=auth_headers)
        names = [s["name"] for s in response.json()]
        assert names[0] == "Java"  # not JavaScript

    async def test_empty_result_for_nonsense(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.get(f"{API}/skills/search?q=zzzqqqxxx", headers=auth_headers)
        assert response.json() == []


class TestManualSkills:
    async def _first_skill_id(self, client: AsyncClient, headers: dict[str, str]) -> str:
        found = await client.get(f"{API}/skills/search?q=python", headers=headers)
        return found.json()[0]["id"]

    async def test_added_skill_is_marked_verified(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # A hand-added skill is verified by definition, which also protects it
        # from a later re-parse.
        skill_id = await self._first_skill_id(client, auth_headers)

        response = await client.post(
            f"{API}/profile/skills",
            headers=auth_headers,
            json={"skill_id": skill_id, "proficiency": "ADVANCED"},
        )

        assert response.status_code == 201
        assert response.json()["is_user_verified"] is True

    async def test_cannot_add_the_same_skill_twice(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        skill_id = await self._first_skill_id(client, auth_headers)
        await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": skill_id}
        )
        again = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": skill_id}
        )
        assert again.status_code == 409

    async def test_unknown_skill_id_returns_404(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    async def test_delete_removes_it(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        skill_id = await self._first_skill_id(client, auth_headers)
        created = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": skill_id}
        )

        await client.delete(f"{API}/profile/skills/{created.json()['id']}", headers=auth_headers)

        assert (await client.get(f"{API}/profile/skills", headers=auth_headers)).json() == []

    async def test_cannot_edit_another_users_skill(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        skill_id = await self._first_skill_id(client, auth_headers)
        created = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": skill_id}
        )

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "thief@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.patch(
            f"{API}/profile/skills/{created.json()['id']}",
            headers=headers,
            json={"proficiency": "EXPERT"},
        )
        assert response.status_code == 404
