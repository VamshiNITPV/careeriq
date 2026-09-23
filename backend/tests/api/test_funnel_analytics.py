"""Application counts and outcome rates (US-7.2)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_application_transitions import apply_to, move
from tests.api.test_job_match import upload_resume
from tests.api.test_jobs import API, posting, submission


async def analytics(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get(f"{API}/applications/analytics", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def applied_job(
    client: AsyncClient, headers: dict[str, str], title: str, company: str = "Acme"
) -> tuple[str, str]:
    """A distinct job with this title, applied to. Returns (job_id, app_id).

    `company` varies the posting body, and must differ between two jobs sharing
    a title: deduplication keys on the description, so submitting the same text
    twice returns the *same* job — and then applying twice is one application,
    not two. Found by asserting a role segment held two and getting one.
    """
    response = await client.post(
        f"{API}/jobs", headers=headers, json=submission(posting(title=title, company=company))
    )
    assert response.status_code == 201, response.text
    job_id = str(response.json()["job"]["id"])
    return job_id, await apply_to(client, headers, job_id)


class TestFunnelAnalytics:
    async def test_an_interview_still_counts_after_a_rejection(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The reason `application_events` exists, stated as a number.

        Rejected *after* an interview is a different outcome from rejected on
        sight, and only the log knows which. Counting current status alone would
        score this as never having reached an interview and make every rate on
        the page quietly too low.
        """
        _, application_id = await applied_job(client, auth_headers, "Backend Engineer")
        await move(client, auth_headers, application_id, "INTERVIEW")
        await move(client, auth_headers, application_id, "REJECTED")

        body = await analytics(client, auth_headers)

        assert body["overall"]["applications"] == 1
        assert body["overall"]["interviews"] == 1

    async def test_a_bookmark_is_not_an_application(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Counting saved jobs would dilute every rate with jobs nothing was
        ever sent to."""
        created = await client.post(
            f"{API}/jobs", headers=auth_headers, json=submission(posting(title="Only Bookmarked"))
        )
        assert created.status_code == 201, created.text
        saved = str(created.json()["job"]["id"])
        response = await client.put(
            f"{API}/jobs/{saved}/application", headers=auth_headers, json={}
        )
        assert response.status_code == 200, response.text

        body = await analytics(client, auth_headers)

        assert body["overall"]["applications"] == 0

    async def test_a_thin_segment_reports_counts_and_no_rate(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """AC3. One interview in two applications is not a 50% rate.

        The counts stay — they are facts. The rate is null, which is not the
        same as 0.0 and must not render as one.
        """
        _, first = await applied_job(client, auth_headers, "Backend Engineer")
        await applied_job(client, auth_headers, "Platform Engineer")
        await move(client, auth_headers, first, "INTERVIEW")

        body = await analytics(client, auth_headers)

        assert body["overall"]["applications"] == 2
        assert body["overall"]["interviews"] == 1
        assert body["overall"]["low_confidence"] is True
        assert body["overall"]["interview_rate"] is None
        assert body["overall"]["offer_rate"] is None
        # Sent so a client can explain the threshold without keeping its own
        # copy, which would drift the day this changes.
        assert body["min_for_rate"] == 5

    async def test_a_rate_appears_once_there_is_enough_to_say(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Five applications, one interview, no offers."""
        ids = []
        for index in range(5):
            _, application_id = await applied_job(client, auth_headers, f"Engineer {index}")
            ids.append(application_id)
        await move(client, auth_headers, ids[0], "INTERVIEW")

        body = await analytics(client, auth_headers)

        assert body["overall"]["applications"] == 5
        assert body["overall"]["low_confidence"] is False
        assert body["overall"]["interview_rate"] == 0.2
        # Zero, not null. "Five applications and none reached an offer" is a
        # real answer; null means "not enough happened to say", and collapsing
        # the two would hide a genuine result behind a caveat.
        assert body["overall"]["offer_rate"] == 0.0

    async def test_slices_by_role_and_offers_all_four(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """AC2, now complete.

        Two of the four used to be absent because the facts were never
        recorded. Migration 0020 records them at the moment of applying, which
        is the only moment they exist — a resume gets edited and the corpus
        moves, so asking later answers a different question.
        """
        await applied_job(client, auth_headers, "Backend Engineer", company="Acme")
        await applied_job(client, auth_headers, "Backend Engineer", company="Zeta Labs")
        await applied_job(client, auth_headers, "Data Engineer", company="Nova")

        body = await analytics(client, auth_headers)

        roles = {segment["label"]: segment["applications"] for segment in body["by_role"]}
        assert roles["Backend Engineer"] == 2
        assert roles["Data Engineer"] == 1
        # Busiest first, so the list does not reorder itself between requests.
        assert body["by_role"][0]["label"] == "Backend Engineer"

        assert body["segments_available"] == [
            "role",
            "location",
            "resume_version",
            "match_score_band",
        ]

    async def test_an_application_with_no_snapshot_is_named_not_counted_out(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Every application filed before 0020 has no resume and no score.

        Dropping them from the two new tables would make those tables disagree
        with the headline count, which reads as a bug. Naming them reads as what
        it is — the information was never captured and cannot be recovered.

        `applied_job` uploads no resume, so these rows are exactly that case.
        """
        await applied_job(client, auth_headers, "Backend Engineer")
        await applied_job(client, auth_headers, "Platform Engineer")

        body = await analytics(client, auth_headers)

        total = body["overall"]["applications"]
        assert total == 2
        for key in ("by_resume", "by_score_band"):
            assert [s["label"] for s in body[key]] == ["Not recorded"], key
            # The sum is the point: a segment table that loses rows is worse
            # than one that admits it does not know about them.
            assert sum(s["applications"] for s in body[key]) == total, key

    async def test_slices_by_the_resume_that_was_sent(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """Labelled for a reader, not by id.

        A column of UUIDs answers no question anybody asked, and "which resume
        worked better" is the whole reason this slice exists.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        await applied_job(client, auth_headers, "Backend Engineer")

        body = await analytics(client, auth_headers)

        assert len(body["by_resume"]) == 1
        label = body["by_resume"][0]["label"]
        assert label != "Not recorded"
        assert label.startswith("v1")
        # And a band, since a score was captured alongside it.
        assert body["by_score_band"][0]["label"] != "Not recorded"

    async def test_another_users_applications_are_not_counted(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A funnel that mixed two job hunts would be worse than none."""
        await applied_job(client, auth_headers, "Backend Engineer")

        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "other-hunter@example.com", "password": "correct-horse-9"},
        )
        assert registered.status_code == 201, registered.text
        other = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

        body = await analytics(client, other)

        assert body["overall"]["applications"] == 0
        assert body["by_role"] == []
