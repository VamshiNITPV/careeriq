"""`GET /skills/gaps` — what the target asks for that the caller lacks (US-5.1).

Against real PostgreSQL, because the aggregate is a grouped query over a joined
set and that is the part most likely to be wrong.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.test_jobs import BACKEND_BODY, NURSE_BODY, submit_job

API = "/api/v1"


async def set_target_roles(client: AsyncClient, headers: dict[str, str], roles: list[str]) -> None:
    response = await client.put(
        f"{API}/profile/preferences",
        headers=headers,
        # PUT replaces the set wholesale, so the other fields are sent empty
        # rather than omitted — that is the endpoint's contract, not an oversight.
        json={"target_roles": roles, "preferred_locations": []},
    )
    assert response.status_code == 200, response.text


class TestAvailability:
    async def test_no_target_roles_is_a_stated_answer(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """An empty list with no explanation reads as "you have no gaps".

        That is congratulation for a completeness nobody measured, and it is the
        same mistake `/recommendations` avoids with its own `availability`.
        """
        response = await client.get(f"{API}/skills/gaps", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["availability"] == "NO_TARGET"
        assert body["items"] == []
        assert body["target_jobs"] == 0

    async def test_roles_that_match_nothing_say_so(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Distinct from NO_TARGET: the user did their part and the corpus has
        nothing, which is a different thing to fix."""
        await set_target_roles(client, auth_headers, ["Underwater Basket Weaver"])

        body = (await client.get(f"{API}/skills/gaps", headers=auth_headers)).json()

        assert body["availability"] == "NO_JOBS"
        assert body["target_roles"] == ["Underwater Basket Weaver"]
        assert body["items"] == []


class TestTheAggregate:
    async def test_it_reports_what_the_target_jobs_ask_for(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/gaps", headers=auth_headers)).json()

        assert body["availability"] == "READY"
        assert body["target_jobs"] == 1
        names = [item["name"] for item in body["items"]]
        assert "Python" in names, names
        # Everything is MISSING for a user with no resume, which is correct
        # rather than a bug: they have claimed no skills.
        assert {item["status"] for item in body["items"]} == {"MISSING"}

    async def test_only_jobs_whose_title_names_the_role_are_counted(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """The denominator is the claim. A nursing post in a backend engineer's
        gap analysis would put its skills on the list and dilute every
        frequency."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/gaps", headers=auth_headers)).json()

        assert body["target_jobs"] == 1
        assert "Nursing" not in [item["name"] for item in body["items"]]

    async def test_a_skill_the_user_holds_is_not_a_gap(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The whole point: the list has to reflect what the reader already has.

        Written through the profile API rather than the resume pipeline, so the
        test states one thing — holding a skill removes it from the gap list —
        without depending on what a fixture resume happens to mention.
        """
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        python_id = await db_session.scalar(text("SELECT id FROM skills WHERE name = 'Python'"))
        added = await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": str(python_id)}
        )
        assert added.status_code in (200, 201), added.text

        body = (await client.get(f"{API}/skills/gaps", headers=auth_headers)).json()

        python = next(item for item in body["items"] if item["name"] == "Python")
        assert python["status"] == "STRONG"

    async def test_severity_rises_with_how_many_target_jobs_ask(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-5.1 AC2 — priority comes from frequency across the target roles,
        not from how common a skill is in the market as a whole."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/gaps", headers=auth_headers)).json()

        python = next(item for item in body["items"] if item["name"] == "Python")
        # The only target job requires it, so it is as urgent as it can be.
        assert python["severity"] == "CRITICAL"
        assert float(python["frequency"]) >= 0.6

    async def test_the_list_leads_with_what_is_missing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A reader scanning this wants the next thing to learn at the top."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])
        python_id = await db_session.scalar(text("SELECT id FROM skills WHERE name = 'Python'"))
        await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": str(python_id)}
        )

        items = (await client.get(f"{API}/skills/gaps", headers=auth_headers)).json()["items"]

        statuses = [item["status"] for item in items]
        assert statuses == sorted(
            statuses, key=lambda s: {"MISSING": 0, "PARTIAL": 1, "STRONG": 2}[s]
        )


class TestAgainstOneJob:
    async def test_a_job_id_narrows_the_target_to_that_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Same code path as the aggregate, over a set of one.

        Two implementations would drift, and the single-job answer would
        eventually disagree with the aggregate that contains it.
        """
        job_id = await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await set_target_roles(client, auth_headers, ["Nurse"])

        body = (
            await client.get(f"{API}/skills/gaps?job_id={job_id}", headers=auth_headers)
        ).json()

        assert body["availability"] == "READY"
        assert body["target_jobs"] == 1
        assert body["job_id"] == job_id
        # The target roles are ignored entirely when a job is named.
        assert "Python" in [item["name"] for item in body["items"]]

    async def test_it_works_without_any_target_roles(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Asking about one job is a complete question on its own — requiring a
        profile setting first would be a dead end on the job page."""
        job_id = await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)

        body = (
            await client.get(f"{API}/skills/gaps?job_id={job_id}", headers=auth_headers)
        ).json()

        assert body["availability"] == "READY"
        assert body["items"]
