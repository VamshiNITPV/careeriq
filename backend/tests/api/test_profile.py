"""API tests for the profile endpoints and resume autofill."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from tests.fixtures.documents import build_pdf

API = "/api/v1"

# A resume whose header carries contact details that differ from anything the
# tests type in, so autofill and never-overwrite can be told apart.
RESUME_WITH_CONTACT = """\
ANANYA IYER
ananya.iyer@example.com | +91 90000 11111 | Pune, India
linkedin.com/in/ananyaiyer | github.com/ananyaiyer

TECHNICAL SKILLS
Python, FastAPI, PostgreSQL, Docker

WORK EXPERIENCE
Backend Engineer, Example Corp
Built and maintained REST APIs in Python.

EDUCATION
B.Tech Computer Science
"""


class TestGetProfile:
    async def test_returns_the_profile_created_at_registration(
        self, client: AsyncClient, auth_headers: dict[str, str], user_payload: dict[str, str]
    ) -> None:
        response = await client.get(f"{API}/profile", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["full_name"] == user_payload["full_name"]

    async def test_array_fields_are_empty_lists_not_null(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Pins the Python-side `default=list` on the ARRAY columns.

        Without it a freshly constructed Profile holds None in memory, and
        `expire_on_commit=False` means a commit never refreshes it — so
        serialising as list[str] raises and the endpoint 500s.
        """
        body = (await client.get(f"{API}/profile", headers=auth_headers)).json()

        assert body["target_roles"] == []
        assert body["preferred_locations"] == []
        assert body["preferred_work_modes"] == []
        assert body["preferred_employment_types"] == []

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get(f"{API}/profile")).status_code == 401

    async def test_creates_a_profile_when_the_row_is_missing(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        # Accounts created outside local registration have no profile row. A
        # 404 for your own profile would be a confusing way to say "empty".
        existing = await db_session.scalar(select(Profile))
        assert existing is not None
        await db_session.delete(existing)
        await db_session.flush()

        response = await client.get(f"{API}/profile", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["full_name"] is None


class TestPatchProfile:
    async def test_updates_only_the_fields_sent(
        self, client: AsyncClient, auth_headers: dict[str, str], user_payload: dict[str, str]
    ) -> None:
        """Pins `model_dump(exclude_unset=True)`.

        Without it every absent optional field arrives as None, and editing one
        field silently clears the other eight.
        """
        response = await client.patch(
            f"{API}/profile", headers=auth_headers, json={"headline": "Backend Engineer"}
        )

        assert response.status_code == 200
        assert response.json()["headline"] == "Backend Engineer"
        assert response.json()["full_name"] == user_payload["full_name"]

    async def test_an_empty_string_clears_a_field(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # A cleared HTML input posts "", not null. Storing it would leave two
        # representations of empty for autofill to reason about.
        await client.patch(f"{API}/profile", headers=auth_headers, json={"headline": "x"})
        response = await client.patch(f"{API}/profile", headers=auth_headers, json={"headline": ""})

        assert response.json()["headline"] is None

    async def test_invalid_country_code_is_422_not_500(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The schema must mirror the CHECK constraint.

        Anything it misses reaches Postgres, raises, and surfaces through the
        catch-all handler as an opaque INTERNAL_ERROR.
        """
        response = await client.patch(
            f"{API}/profile", headers=auth_headers, json={"country_code": "INDIA"}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_country_code_is_upper_cased(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            f"{API}/profile", headers=auth_headers, json={"country_code": "in"}
        )
        assert response.json()["country_code"] == "IN"

    async def test_a_url_without_a_scheme_is_accepted(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # People write "linkedin.com/in/priya". Rejecting that is pedantry.
        response = await client.patch(
            f"{API}/profile", headers=auth_headers, json={"linkedin_url": "linkedin.com/in/priya"}
        )

        assert response.status_code == 200
        assert response.json()["linkedin_url"].startswith("https://")

    async def test_a_nonsense_url_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            f"{API}/profile", headers=auth_headers, json={"github_url": "not a url at all"}
        )
        assert response.status_code == 422

    async def test_an_overlong_name_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # String(200) in the column; without a schema bound this is a DataError.
        response = await client.patch(
            f"{API}/profile", headers=auth_headers, json={"full_name": "a" * 300}
        )
        assert response.status_code == 422

    async def test_one_user_cannot_affect_another(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.patch(f"{API}/profile", headers=auth_headers, json={"full_name": "First User"})

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "second@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        assert (await client.get(f"{API}/profile", headers=headers)).json()["full_name"] is None


class TestPreferences:
    async def test_put_replaces_wholesale(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT, not PATCH — the reason these are a separate endpoint.

        With PATCH over list fields, "clear this list" and "leave it alone" are
        the same payload.
        """
        await client.put(
            f"{API}/profile/preferences",
            headers=auth_headers,
            json={"target_roles": ["Backend Engineer", "ML Engineer"]},
        )
        response = await client.put(
            f"{API}/profile/preferences",
            headers=auth_headers,
            json={"target_roles": ["Data Engineer"]},
        )

        assert response.json()["target_roles"] == ["Data Engineer"]

    async def test_duplicates_are_removed_and_order_preserved(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.put(
            f"{API}/profile/preferences",
            headers=auth_headers,
            json={"target_roles": ["Backend", "ML", "backend", "  ", "ML"]},
        )
        assert response.json()["target_roles"] == ["Backend", "ML"]

    async def test_saving_bumps_the_cache_key(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # preferences_updated_at is the recommendation cache key (ADR-008).
        response = await client.put(
            f"{API}/profile/preferences", headers=auth_headers, json={"target_roles": ["Backend"]}
        )
        assert response.json()["preferences_updated_at"] is not None

    async def test_a_no_op_save_does_not_bump_the_cache_key(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Invalidating every cached ranking because someone opened and closed a
        # settings form would be pure waste.
        payload = {"target_roles": ["Backend"]}
        first = await client.put(f"{API}/profile/preferences", headers=auth_headers, json=payload)
        second = await client.put(f"{API}/profile/preferences", headers=auth_headers, json=payload)

        assert first.json()["preferences_updated_at"] == second.json()["preferences_updated_at"]

    async def test_salary_requires_a_currency(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # An unlabelled number is useless to the ranking formula.
        response = await client.put(
            f"{API}/profile/preferences",
            headers=auth_headers,
            json={"min_salary_expectation": "1200000"},
        )
        assert response.status_code == 422

    async def test_currency_is_upper_cased(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.put(
            f"{API}/profile/preferences",
            headers=auth_headers,
            json={"min_salary_expectation": "1200000", "salary_currency": "inr"},
        )
        assert response.json()["salary_currency"] == "INR"

    async def test_an_unknown_enum_member_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.put(
            f"{API}/profile/preferences",
            headers=auth_headers,
            json={"preferred_work_modes": ["UNDERWATER"]},
        )
        assert response.status_code == 422


class TestRoutingRegression:
    async def test_profile_skills_still_resolves(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """/profile and /profile/skills are two separate routers.

        This stays safe only while neither declares a path parameter directly
        under /profile — a GET /profile/{id} would swallow /profile/skills.
        """
        assert (await client.get(f"{API}/profile/skills", headers=auth_headers)).status_code == 200


class TestResumeAutofill:
    async def _upload_and_parse(self, client, auth_headers, run_pipeline) -> None:
        files = {"file": ("cv.pdf", build_pdf(RESUME_WITH_CONTACT), "application/pdf")}
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=files)
        await run_pipeline(uuid.UUID(upload.json()["version_id"]))

    async def test_fills_empty_fields_from_the_resume(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int, run_pipeline
    ) -> None:
        before = (await client.get(f"{API}/profile", headers=auth_headers)).json()
        assert before["location"] is None

        await self._upload_and_parse(client, auth_headers, run_pipeline)

        after = (await client.get(f"{API}/profile", headers=auth_headers)).json()
        assert after["location"] == "Pune, India"
        assert after["phone"] == "+91 90000 11111"
        assert after["linkedin_url"] == "https://www.linkedin.com/in/ananyaiyer"

    async def test_never_overwrites_what_the_user_typed(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int, run_pipeline
    ) -> None:
        """The single most important test in this feature.

        Both halves matter. Asserting only that typed values survive would pass
        against an implementation that does nothing at all, so this also checks
        that the empty fields really were filled.
        """
        await client.patch(
            f"{API}/profile",
            headers=auth_headers,
            json={"phone": "+91 12345 67890", "location": "Hyderabad, India"},
        )

        await self._upload_and_parse(client, auth_headers, run_pipeline)

        after = (await client.get(f"{API}/profile", headers=auth_headers)).json()
        # Typed values win, even though the resume says something different.
        assert after["phone"] == "+91 12345 67890"
        assert after["location"] == "Hyderabad, India"
        # ...and fields that were empty did get filled.
        assert after["linkedin_url"] == "https://www.linkedin.com/in/ananyaiyer"
        assert after["github_url"] == "https://github.com/ananyaiyer"

    async def test_registration_name_is_treated_as_user_entered(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int, run_pipeline
    ) -> None:
        # services/auth.py sets full_name from the register payload, so for the
        # standard fixture the name is already non-empty and autofill must not
        # replace it with the name on the resume.
        await self._upload_and_parse(client, auth_headers, run_pipeline)

        after = (await client.get(f"{API}/profile", headers=auth_headers)).json()
        assert after["full_name"] == "Priya S."
        assert after["full_name"] != "Ananya Iyer"

    async def test_fills_the_name_when_registration_supplied_none(
        self, client: AsyncClient, seeded_skills: int, run_pipeline
    ) -> None:
        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "noname@example.com", "password": "correct-horse-9"},
        )
        headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

        await self._upload_and_parse(client, headers, run_pipeline)

        assert (await client.get(f"{API}/profile", headers=headers)).json()[
            "full_name"
        ] == "Ananya Iyer"

    async def test_is_idempotent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        # /reparse exists, so a second run must be a no-op rather than churning
        # the profile.
        files = {"file": ("cv.pdf", build_pdf(RESUME_WITH_CONTACT), "application/pdf")}
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=files)
        version_id = uuid.UUID(upload.json()["version_id"])

        first = await run_pipeline(version_id)
        assert first.contact_fields_filled > 0

        from app.models.resume import ResumeVersion

        version = await db_session.get(ResumeVersion, version_id)
        assert version is not None
        version.processing_status = version.processing_status.PENDING
        await db_session.commit()

        second = await run_pipeline(version_id)
        assert second.contact_fields_filled == 0

    async def test_records_what_was_applied_and_skipped(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int, run_pipeline
    ) -> None:
        # So "why didn't my name update?" is answerable without a debugger.
        await client.patch(f"{API}/profile", headers=auth_headers, json={"phone": "+1 555 0100"})

        files = {"file": ("cv.pdf", build_pdf(RESUME_WITH_CONTACT), "application/pdf")}
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=files)
        version_id = upload.json()["version_id"]
        await run_pipeline(uuid.UUID(version_id))

        detail = await client.get(f"{API}/resumes/versions/{version_id}", headers=auth_headers)
        contact = detail.json()["parsed_entities"]["contact"]

        assert "phone" in contact["skipped"]
        assert "location" in contact["applied"]

    async def test_an_unparseable_header_does_not_fail_the_parse(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int, run_pipeline
    ) -> None:
        # Contact extraction is a bonus; a regex edge case must never cost the
        # user their skills.
        noisy = "░▒▓ ██\n\nTECHNICAL SKILLS\nPython, Docker\n\nEXPERIENCE\nBuilt things.\n" * 3
        files = {"file": ("cv.pdf", build_pdf(noisy), "application/pdf")}
        upload = await client.post(f"{API}/resumes", headers=auth_headers, files=files)

        result = await run_pipeline(uuid.UUID(upload.json()["version_id"]))

        assert result.status.value == "COMPLETE"
        assert result.skills_written > 0
