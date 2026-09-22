"""Moving an application along the funnel (US-7.1).

Separate from `test_applications.py`, which covers US-7.0 — the bookmark and the
applied flag. That endpoint is an idempotent PUT of two booleans; this one is a
PATCH that asks for a *change* and is refused when the funnel disallows it, so
the two have opposite properties and testing them together invites asserting one
endpoint's rules against the other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from tests.api.test_applications import make_job
from tests.api.test_jobs import API


async def apply_to(client: AsyncClient, headers: dict[str, str], job_id: str) -> str:
    """Mark a job applied and return the application's id."""
    response = await client.put(
        f"{API}/jobs/{job_id}/application",
        headers=headers,
        json={"saved": True, "applied": True},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


async def move(
    client: AsyncClient,
    headers: dict[str, str],
    application_id: str,
    status: str,
    **extra: object,
) -> Response:
    return await client.patch(
        f"{API}/applications/{application_id}/status",
        headers=headers,
        json={"status": status, **extra},
    )


class TestChangingStatus:
    async def test_a_move_forward_is_recorded_with_its_event(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """AC2: every transition writes an event.

        Asserted against the database rather than the response, because a
        response can report a move the log never received — which is exactly the
        failure that would make US-7.2's analytics quietly wrong while every
        screen looked correct.
        """
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)

        response = await move(client, auth_headers, application_id, "INTERVIEW")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "INTERVIEW"

        rows = (
            await db_session.execute(
                text(
                    "SELECT from_status, to_status FROM application_events "
                    "WHERE application_id = :id ORDER BY occurred_at"
                ),
                {"id": uuid.UUID(application_id)},
            )
        ).all()
        assert [tuple(r) for r in rows] == [("APPLIED", "INTERVIEW")]

    async def test_a_disallowed_move_is_409_and_says_where_it_can_go(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """409 rather than 422: the body is well formed, the state refuses it.

        The response carries the allowed set so a client can rebuild its options
        from the error rather than hard-coding the funnel a second time.
        """
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)
        assert (await move(client, auth_headers, application_id, "REJECTED")).status_code == 200

        # REJECTED is an ending. The only way out of it is reopening.
        response = await move(client, auth_headers, application_id, "OFFER")

        assert response.status_code == 409, response.text
        # The single error envelope every endpoint uses (api.md 1.4), not
        # FastAPI's own `detail` shape.
        error = response.json()["error"]
        assert error["code"] == "INVALID_STATUS_TRANSITION"
        assert error["details"]["current"] == "REJECTED"
        assert error["details"]["allowed"] == ["APPLIED"]

    async def test_repeating_a_move_is_refused(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Deliberately not idempotent, unlike the bookmark PUT beside it.

        Staying put is not a transition, and an event recording that nothing
        happened is noise in a log whose entire worth is the opposite.
        """
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)

        first = await move(client, auth_headers, application_id, "ASSESSMENT")
        second = await move(client, auth_headers, application_id, "ASSESSMENT")

        assert first.status_code == 200, first.text
        assert second.status_code == 409

    async def test_another_users_application_is_404_not_403(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """403 would confirm the row exists, which over a guessable id space
        leaks who applied to what. The two cases have to look identical."""
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)

        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "someone-else@example.com", "password": "correct-horse-9"},
        )
        assert registered.status_code == 201, registered.text
        intruder = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

        response = await move(client, intruder, application_id, "INTERVIEW")

        assert response.status_code == 404

    async def test_back_to_saved_is_refused_when_never_bookmarked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The one allowed move the row constraints make impossible.

        Refused rather than smoothed over by quietly setting `is_saved`:
        recording one fact must never rewrite the other, which is why the
        bookmark PUT was split into two booleans in the first place.
        """
        job_id = await make_job(client, auth_headers)
        created = await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": False, "applied": True},
        )
        assert created.status_code == 200, created.text
        application_id = str(created.json()["id"])

        refused = await move(client, auth_headers, application_id, "SAVED")

        assert refused.status_code == 409
        assert "delete" in refused.json()["error"]["message"].lower()

        # And nothing moved. A refused transition must leave the row alone
        # rather than half-applying itself.
        row = await db_session.scalar(
            select(Application).where(Application.id == uuid.UUID(application_id))
        )
        assert row is not None
        await db_session.refresh(row)
        assert row.status.value == "APPLIED"
        assert row.is_saved is False

    async def test_a_reported_time_is_kept_rather_than_the_clock(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """People log an interview the evening after it happened.

        `occurred_at` is a separate column from `created_at` precisely so the
        funnel measures someone's job hunt rather than their record-keeping.
        """
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)
        happened = datetime.now(UTC) - timedelta(days=3)

        response = await move(
            client,
            auth_headers,
            application_id,
            "INTERVIEW",
            occurred_at=happened.isoformat(),
        )

        assert response.status_code == 200, response.text
        stored = await db_session.scalar(
            text(
                "SELECT occurred_at FROM application_events "
                "WHERE application_id = :id AND to_status = 'INTERVIEW'"
            ),
            {"id": uuid.UUID(application_id)},
        )
        assert stored is not None
        assert abs((stored - happened).total_seconds()) < 1

    async def test_a_future_time_is_refused(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A funnel measures elapsed time between events. One dated ahead of now
        produces negative durations that downstream arithmetic cannot tell apart
        from a bug in itself."""
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)

        response = await move(
            client,
            auth_headers,
            application_id,
            "INTERVIEW",
            occurred_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        )

        assert response.status_code == 422

    async def test_returning_to_saved_clears_the_applied_timestamp(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """`applied_has_timestamp` wants NULL at SAVED and a value past it.

        A transition that did not maintain this would fail at the database with
        a constraint violation surfacing as an opaque 500, rather than working.
        """
        job_id = await make_job(client, auth_headers)
        application_id = await apply_to(client, auth_headers, job_id)

        back = await move(client, auth_headers, application_id, "SAVED")

        assert back.status_code == 200, back.text
        assert back.json()["applied_at"] is None

        # And forward again refills it, or the row could never leave SAVED twice.
        forward = await move(client, auth_headers, application_id, "APPLIED")
        assert forward.status_code == 200, forward.text
        assert forward.json()["applied_at"] is not None
