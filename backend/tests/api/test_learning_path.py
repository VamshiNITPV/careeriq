"""`GET /skills/learning-path` — the ordered plan (US-5.2).

The ordering itself is unit-tested in `test_learning_plan.py`, where it is pure.
These cover the wiring: that the plan is built from the caller's real gaps, and
that the three empty cases stay distinguishable.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.test_jobs import BACKEND_BODY, submit_job
from tests.api.test_skill_gaps import set_target_roles

API = "/api/v1"


class TestAvailability:
    async def test_no_target_roles_says_so(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        assert body["availability"] == "NO_TARGET"
        assert body["steps"] == []
        assert body["total_hours"] == 0

    async def test_roles_matching_nothing_are_distinct_from_no_roles(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await set_target_roles(client, auth_headers, ["Underwater Basket Weaver"])

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        assert body["availability"] == "NO_JOBS"


class TestThePlan:
    async def test_it_builds_steps_from_the_caller_s_gaps(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        assert body["availability"] == "READY"
        assert body["steps"], body
        names = [step["name"] for step in body["steps"]]
        assert "Python" in names

    async def test_every_step_carries_an_outcome_and_an_estimate(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-5.2 AC2. A step with nothing to check is worse than no step."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        for step in body["steps"]:
            assert step["outcome"].strip(), step
            assert step["estimated_hours"] > 0, step
            # Never a restatement of the skill name.
            assert step["outcome"].lower() != f"learn {step['name'].lower()}"

    async def test_positions_are_contiguous_and_start_at_one(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        assert [s["position"] for s in body["steps"]] == list(range(1, len(body["steps"]) + 1))

    async def test_total_hours_matches_the_steps(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        assert body["total_hours"] == sum(s["estimated_hours"] for s in body["steps"])

    async def test_a_skill_the_caller_has_is_not_a_step(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A plan that opens with something you can already do is one a reader
        stops trusting."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])
        python_id = await db_session.scalar(text("SELECT id FROM skills WHERE name = 'Python'"))
        await client.post(
            f"{API}/profile/skills", headers=auth_headers, json={"skill_id": str(python_id)}
        )

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()

        assert "Python" not in [step["name"] for step in body["steps"]]

    async def test_a_prerequisite_never_follows_what_needs_it(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """The property that makes the plan followable, asserted end to end
        rather than only in the pure unit test."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        steps = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()[
            "steps"
        ]

        position = {step["name"]: step["position"] for step in steps}
        for step in steps:
            for earlier in step["after"]:
                assert position[earlier] < step["position"], f"{earlier} after {step['name']}"

    async def test_a_job_id_plans_for_that_job_alone(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        job_id = await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)

        body = (
            await client.get(f"{API}/skills/learning-path?job_id={job_id}", headers=auth_headers)
        ).json()

        assert body["availability"] == "READY"
        assert body["job_id"] == job_id
        assert body["steps"]
