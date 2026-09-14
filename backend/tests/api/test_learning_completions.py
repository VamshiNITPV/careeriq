"""Ticking a learning step off (US-5.2).

The plan is derived on every request; a tick is a decision and has to outlive
that. These cover the seam between the two.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.test_jobs import BACKEND_BODY, submit_job
from tests.api.test_skill_gaps import set_target_roles

API = "/api/v1"


async def a_step(client: AsyncClient, headers: dict[str, str]) -> dict:
    await submit_job(client, headers, "Senior Backend Engineer", BACKEND_BODY)
    await set_target_roles(client, headers, ["Backend Engineer"])
    body = (await client.get(f"{API}/skills/learning-path", headers=headers)).json()
    assert body["steps"], body
    return body["steps"][0]


class TestTheToggle:
    async def test_a_tick_survives_the_plan_being_rebuilt(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """The whole reason the table exists.

        The plan is recomputed from scratch on every request, so a tick stored
        alongside it would be undone by the next job fetch.
        """
        step = await a_step(client, auth_headers)

        marked = await client.put(
            f"{API}/skills/learning-path/steps/{step['skill_id']}",
            headers=auth_headers,
            json={"completed": True},
        )
        assert marked.status_code == 200, marked.text

        again = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()
        row = next(s for s in again["steps"] if s["skill_id"] == step["skill_id"])
        assert row["completed"] is True

    async def test_it_can_be_put_back(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        step = await a_step(client, auth_headers)
        url = f"{API}/skills/learning-path/steps/{step['skill_id']}"

        await client.put(url, headers=auth_headers, json={"completed": True})
        await client.put(url, headers=auth_headers, json={"completed": False})

        again = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()
        row = next(s for s in again["steps"] if s["skill_id"] == step["skill_id"])
        assert row["completed"] is False

    async def test_repeating_it_changes_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A checkbox someone taps twice on a phone must not become an error, and
        must not duplicate the row."""
        step = await a_step(client, auth_headers)
        url = f"{API}/skills/learning-path/steps/{step['skill_id']}"

        first = await client.put(url, headers=auth_headers, json={"completed": True})
        second = await client.put(url, headers=auth_headers, json={"completed": True})

        assert first.status_code == second.status_code == 200
        count = await db_session.scalar(
            text("SELECT count(*) FROM learning_step_completions WHERE skill_id = :s"),
            {"s": uuid.UUID(step["skill_id"])},
        )
        assert count == 1

    async def test_an_unknown_skill_is_404_and_writes_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Pins the check-before-write ordering. Without it the RESTRICT foreign
        key rejects the insert and surfaces as an opaque 500."""
        response = await client.put(
            f"{API}/skills/learning-path/steps/{uuid.uuid4()}",
            headers=auth_headers,
            json={"completed": True},
        )

        assert response.status_code == 404
        assert await db_session.scalar(text("SELECT count(*) FROM learning_step_completions")) == 0

    async def test_a_tick_does_not_put_the_skill_on_the_profile(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Studying a skill and claiming it are different assertions.

        Adding it to the profile on a checkbox would be the interface asserting
        something about the user that they did not.
        """
        step = await a_step(client, auth_headers)

        await client.put(
            f"{API}/skills/learning-path/steps/{step['skill_id']}",
            headers=auth_headers,
            json={"completed": True},
        )

        on_profile = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert step["name"] not in [row["skill"]["name"] for row in on_profile]


class TestItChangesThePlan:
    async def test_a_finished_prerequisite_still_precedes_what_needs_it(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Ticking a prerequisite must not break the ordering it created.

        The first version of this test asserted that a completed prerequisite
        *disappears* from its dependants' `after` list. That was wrong about the
        field: `after` names steps **in this plan**, and a ticked step is still in
        the plan — shown, struck through — so referencing it still explains why
        the later step sits where it does. What must hold is the ordering, which
        is what is asserted now.
        """
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])

        before = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()
        first = before["steps"][0]

        await client.put(
            f"{API}/skills/learning-path/steps/{first['skill_id']}",
            headers=auth_headers,
            json={"completed": True},
        )

        steps = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()[
            "steps"
        ]
        position = {row["name"]: row["position"] for row in steps}
        for row in steps:
            for earlier in row["after"]:
                assert position[earlier] < row["position"], f"{earlier} after {row['name']}"

    async def test_finished_steps_come_first(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Otherwise a completed prerequisite can be listed *after* the step it
        unblocked, which reads as a broken order."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await set_target_roles(client, auth_headers, ["Backend Engineer"])
        steps = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()[
            "steps"
        ]
        if len(steps) < 2:
            return

        await client.put(
            f"{API}/skills/learning-path/steps/{steps[1]['skill_id']}",
            headers=auth_headers,
            json={"completed": True},
        )

        after = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()[
            "steps"
        ]
        flags = [row["completed"] for row in after]
        assert flags == sorted(flags, reverse=True), after

    async def test_remaining_hours_discount_what_is_done(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        step = await a_step(client, auth_headers)

        await client.put(
            f"{API}/skills/learning-path/steps/{step['skill_id']}",
            headers=auth_headers,
            json={"completed": True},
        )

        body = (await client.get(f"{API}/skills/learning-path", headers=auth_headers)).json()
        assert body["remaining_hours"] == body["total_hours"] - step["estimated_hours"]
