"""Editing extracted work history, education, projects and certifications.

US-2.4 AC1 — every extracted field is editable. Extraction is heuristic reading
of wildly variable layouts, so it will be wrong sometimes; without an edit path
a wrong row is permanent and is scored against every job the user sees.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import WorkExperience
from tests.fixtures.documents import build_pdf

API = "/api/v1"


def pdf_upload() -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("resume.pdf", build_pdf(), "application/pdf")}


EXPERIENCE = {
    "title": "Staff Engineer",
    "company_name": "Zeta Labs",
    "start_date": "2021-03-01",
    "is_current": True,
    "highlights": ["Led the payments rewrite"],
}


class TestReadingWhatWasExtracted:
    async def test_career_summary_returns_everything_in_one_response(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # Four round trips to fill one screen is four chances for a partial
        # render.
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        summary = await client.get(f"{API}/profile/career", headers=auth_headers)
        assert summary.status_code == 200
        body = summary.json()
        assert len(body["experiences"]) >= 2
        assert len(body["education"]) == 1
        assert body["certifications"]

    async def test_extracted_rows_say_where_they_came_from(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # So the interface can distinguish a parser's reading from the user's
        # own words rather than presenting them identically.
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        version_id = response.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        rows = (await client.get(f"{API}/profile/experience", headers=auth_headers)).json()
        assert rows
        assert all(row["source_version_id"] == version_id for row in rows)
        assert all(row["is_user_verified"] is False for row in rows)
        assert all(row["extraction_confidence"] is not None for row in rows)

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get(f"{API}/profile/experience")).status_code == 401


class TestEditing:
    async def test_correcting_a_row_marks_it_verified(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        rows = (await client.get(f"{API}/profile/experience", headers=auth_headers)).json()
        target = rows[0]

        patched = await client.patch(
            f"{API}/profile/experience/{target['id']}",
            headers=auth_headers,
            json={"company_name": "Zenith Systems Private Limited"},
        )

        assert patched.status_code == 200
        assert patched.json()["company_name"] == "Zenith Systems Private Limited"
        # What protects the edit from the next re-parse.
        assert patched.json()["is_user_verified"] is True

    async def test_a_partial_patch_leaves_the_other_fields_alone(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # Pins exclude_unset. Without it a one-field edit arrives with every
        # other field set to None and wipes the row.
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        rows = (await client.get(f"{API}/profile/experience", headers=auth_headers)).json()
        target = rows[0]

        patched = await client.patch(
            f"{API}/profile/experience/{target['id']}",
            headers=auth_headers,
            json={"location": "Remote"},
        )

        assert patched.json()["title"] == target["title"]
        assert patched.json()["highlights"] == target["highlights"]
        assert patched.json()["start_date"] == target["start_date"]

    async def test_the_parse_identity_survives_an_edit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """content_key must not follow the user's wording.

        It identifies the entity to the parser. Recomputing it because someone
        tidied a company name would leave the next parse with no match, and it
        would insert a second row beside the corrected one.
        """
        response = await client.post(f"{API}/resumes", headers=auth_headers, files=pdf_upload())
        await run_pipeline(uuid.UUID(response.json()["version_id"]))

        rows = (await client.get(f"{API}/profile/experience", headers=auth_headers)).json()
        entity_id = uuid.UUID(rows[0]["id"])
        before = await db_session.get(WorkExperience, entity_id)
        assert before is not None
        original_key = before.content_key

        await client.patch(
            f"{API}/profile/experience/{entity_id}",
            headers=auth_headers,
            json={"company_name": "Something Else Entirely"},
        )

        await db_session.refresh(before)
        assert before.content_key == original_key

    async def test_rejects_an_incoherent_date_range(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # 422 naming the problem, not a 500 from the CHECK constraint.
        response = await client.post(
            f"{API}/profile/experience",
            headers=auth_headers,
            json={
                **EXPERIENCE,
                "is_current": False,
                "start_date": "2022-01-01",
                "end_date": "2020-01-01",
            },
        )
        assert response.status_code == 422

    async def test_rejects_something_both_current_and_ended(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            f"{API}/profile/experience",
            headers=auth_headers,
            json={**EXPERIENCE, "is_current": True, "end_date": "2024-01-01"},
        )
        assert response.status_code == 422


class TestAddingByHand:
    async def test_creates_a_verified_entry_with_no_source(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            f"{API}/profile/experience", headers=auth_headers, json=EXPERIENCE
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Staff Engineer"
        assert body["is_user_verified"] is True
        # No source version: it was never about a particular document, so it
        # survives any resume being deleted.
        assert body["source_version_id"] is None

    async def test_creates_each_entity_type(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payloads = {
            "education": {"institution": "NIT Warangal", "degree": "B.Tech"},
            "projects": {"name": "CareerIQ", "description": "A job matching platform"},
            "certifications": {"name": "AWS Solutions Architect", "issuer": "AWS"},
        }
        for path, payload in payloads.items():
            response = await client.post(
                f"{API}/profile/{path}", headers=auth_headers, json=payload
            )
            assert response.status_code == 201, f"{path}: {response.text}"

    async def test_removing_an_entry(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        created = await client.post(
            f"{API}/profile/experience", headers=auth_headers, json=EXPERIENCE
        )
        entity_id = created.json()["id"]

        removed = await client.delete(
            f"{API}/profile/experience/{entity_id}", headers=auth_headers
        )
        assert removed.status_code == 200
        assert (await client.get(f"{API}/profile/experience", headers=auth_headers)).json() == []


class TestOwnership:
    async def test_another_users_entry_is_404_not_403(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # 403 would confirm the id exists and allow enumeration (US-1.5 AC1).
        created = await client.post(
            f"{API}/profile/experience", headers=auth_headers, json=EXPERIENCE
        )
        entity_id = created.json()["id"]

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "intruder-career@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        assert (
            await client.patch(
                f"{API}/profile/experience/{entity_id}", headers=headers, json={"title": "Hacked"}
            )
        ).status_code == 404
        assert (
            await client.delete(f"{API}/profile/experience/{entity_id}", headers=headers)
        ).status_code == 404

    async def test_lists_are_scoped_to_the_caller(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(f"{API}/profile/experience", headers=auth_headers, json=EXPERIENCE)

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "separate-career@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        assert (await client.get(f"{API}/profile/experience", headers=headers)).json() == []

    async def test_unknown_id_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            f"{API}/profile/experience/{uuid.uuid4()}", headers=auth_headers, json={"title": "x"}
        )
        assert response.status_code == 404


class TestExistingProfileRoutesStillResolve:
    async def test_profile_and_skills_are_not_shadowed(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Three routers now serve /profile. None declares a bare path parameter,
        # which is the only reason that is safe.
        assert (await client.get(f"{API}/profile", headers=auth_headers)).status_code == 200
        assert (await client.get(f"{API}/profile/skills", headers=auth_headers)).status_code == 200
