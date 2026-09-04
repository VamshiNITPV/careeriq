"""Job ingestion, browsing and import (Epic 3)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.job import Company, Job
from app.models.user import User

API = "/api/v1"


def posting(
    *,
    title: str = "Senior Backend Engineer",
    company: str = "Acme Technologies Pvt Ltd",
    extra: str = "",
) -> str:
    """A description long enough and structured enough to parse."""
    return f"""{title}

About us
{company} builds payments infrastructure for teams across India and beyond.
We are a small engineering group that ships continuously.

Location: Bengaluru, India (Hybrid)

Responsibilities
- Design and build backend services in Python
- Own services end to end, from schema to deploy
- Review code and mentor other engineers

Requirements
- 5+ years of professional backend experience
- Strong Python and PostgreSQL
- Bachelor's degree in Computer Science or equivalent

Nice to have
- Exposure to Kubernetes
- Familiarity with Docker in production

What we offer
- Compensation: 25 - 40 LPA
- Health cover for you and your family
{extra}
"""


async def make_admin(db_session: AsyncSession, email: str) -> None:
    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    user.role = UserRole.ADMIN
    await db_session.commit()


class TestSubmitJob:
    async def test_parses_a_pasted_description(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.1 AC2 — every field the acceptance criterion names."""
        response = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": posting()}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["is_duplicate"] is False

        job = body["job"]
        assert job["title"] == "Senior Backend Engineer"
        assert job["company"]["name"] == "Acme Technologies Pvt Ltd"
        assert job["location"] == "Bengaluru, India"
        assert job["work_mode"] == "HYBRID"
        assert job["experience_level"] == "SENIOR"
        assert job["min_years_experience"] == "5.0"
        assert job["min_education"] == "BACHELORS"
        assert job["salary_min"] == "2500000.00"
        assert job["salary_max"] == "4000000.00"
        assert job["salary_currency"] == "INR"
        assert job["salary_period"] == "YEARLY"

    async def test_splits_required_from_preferred_skills(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The only signal the ranking formula has for weighting a skill.
        response = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": posting()}
        )
        skills = {s["name"]: s["requirement"] for s in response.json()["job"]["skills"]}

        assert skills["Python"] == "REQUIRED"
        assert skills["PostgreSQL"] == "REQUIRED"
        assert skills["Kubernetes"] == "PREFERRED"
        # "Familiarity with Docker" is hedged, even though it sits under a
        # nice-to-have heading — both routes agree here.
        assert skills["Docker"] == "PREFERRED"

    async def test_extracts_bullets_into_arrays(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        job = (
            await client.post(f"{API}/jobs", headers=auth_headers, json={"description": posting()})
        ).json()["job"]

        assert any("backend services" in r for r in job["responsibilities"])
        assert any("years" in r for r in job["requirements"])
        assert any("Health cover" in b for b in job["benefits"])

    async def test_supplied_title_and_company_win(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The person pasting knows what they pasted. A heuristic that overrules
        # them is infuriating.
        response = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={
                "description": posting(),
                "title": "Staff Engineer, Payments",
                "company": "Zeta Labs",
            },
        )
        job = response.json()["job"]
        assert job["title"] == "Staff Engineer, Payments"
        assert job["company"]["name"] == "Zeta Labs"

    async def test_rejects_text_too_short_to_be_a_posting(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # 422 with a message for the person who pasted it, not a 500 or a row
        # that scores against every candidate on no evidence.
        response = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": "Backend Engineer"}
        )
        assert response.status_code == 422
        assert "too short" in response.json()["error"]["message"].lower()

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/jobs", json={"description": posting()})
        assert response.status_code == 401


class TestDeduplication:
    async def test_the_same_posting_returns_the_existing_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.2 AC2 — links to the canonical job rather than creating a row."""
        first = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": posting()}
        )
        second = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": posting()}
        )

        assert second.json()["is_duplicate"] is True
        assert second.json()["job"]["id"] == first.json()["job"]["id"]

        listing = await client.get(f"{API}/jobs", headers=auth_headers)
        assert listing.json()["total"] == 1

    async def test_reformatted_reposts_are_caught(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The same posting copied from two sites differs in wrapping and quote
        # characters, not in content. Stage-one hashing has to see through that
        # or every re-post falls through to the expensive comparison.
        original = posting()
        # U+2019 is the curly apostrophe a copy-paste from a job board
        # substitutes, without changing a word of the posting.
        reformatted = original.replace("\n", "\n\n").replace("'", "\u2019").upper()

        await client.post(f"{API}/jobs", headers=auth_headers, json={"description": original})
        second = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": reformatted}
        )
        assert second.json()["is_duplicate"] is True

    async def test_a_different_posting_creates_a_new_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await client.post(f"{API}/jobs", headers=auth_headers, json={"description": posting()})
        second = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={"description": posting(title="Frontend Engineer", extra="- Build UIs in React")},
        )
        assert second.json()["is_duplicate"] is False

        listing = await client.get(f"{API}/jobs", headers=auth_headers)
        assert listing.json()["total"] == 2


class TestCompanyResolution:
    async def test_variants_of_a_name_resolve_to_one_company(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        # Fragmenting an employer would break the "same company" scoping that
        # near-duplicate detection depends on in Phase 6.
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={"description": posting(title="Role One"), "company": "Acme, Inc."},
        )
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={"description": posting(title="Role Two"), "company": "ACME Inc"},
        )

        companies = list((await db_session.scalars(select(Company))).all())
        assert len(companies) == 1

    async def test_distinct_companies_stay_distinct(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={"description": posting(title="Role One"), "company": "Acme Health"},
        )
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={"description": posting(title="Role Two"), "company": "Acme Motors"},
        )

        companies = list((await db_session.scalars(select(Company))).all())
        assert len(companies) == 2


class TestBrowse:
    async def test_lists_and_filters(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await client.post(f"{API}/jobs", headers=auth_headers, json={"description": posting()})
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json={
                "description": posting(title="Frontend Engineer").replace("Hybrid", "Remote"),
                "title": "Frontend Engineer",
            },
        )

        everything = await client.get(f"{API}/jobs", headers=auth_headers)
        assert everything.json()["total"] == 2

        remote = await client.get(f"{API}/jobs?work_mode=REMOTE", headers=auth_headers)
        assert remote.json()["total"] == 1
        assert remote.json()["items"][0]["title"] == "Frontend Engineer"

        searched = await client.get(f"{API}/jobs?q=Frontend", headers=auth_headers)
        assert searched.json()["total"] == 1

        # The seniority filter is no longer called by the UI, which now filters
        # on years — but it is still a documented API filter, and one nothing
        # else covers. Untested and uncalled is how a filter rots into a lie in
        # the docs.
        senior = await client.get(f"{API}/jobs?experience_level=SENIOR", headers=auth_headers)
        assert senior.json()["total"] == 1
        assert senior.json()["items"][0]["title"] == "Senior Backend Engineer"

    async def test_filters_by_years_of_experience(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """A stated range is a gate; an unstated one is not.

        Covers all three storage shapes the parser can produce: a floor with no
        ceiling, an explicit two-sided range, and nothing at all.
        """
        stated = "5+ years of professional backend experience"
        for title, years in (
            ("Open Ended Engineer", stated),  # min 5, max NULL
            ("Bounded Engineer", "3-6 years of professional backend experience"),  # 3 to 6
            ("Unstated Engineer", "Deep professional backend experience"),  # both NULL
        ):
            response = await client.post(
                f"{API}/jobs",
                headers=auth_headers,
                json={
                    "description": posting(title=title).replace(stated, years),
                    "title": title,
                },
            )
            assert response.status_code == 201, response.text

        async def titles(query: str) -> set[str]:
            body = (await client.get(f"{API}/jobs?{query}", headers=auth_headers)).json()
            return {item["title"] for item in body["items"]}

        # Inside 3-6, below the 5+ floor, and never ruled out by the posting
        # that named no number at all.
        assert await titles("years_experience=4") == {"Bounded Engineer", "Unstated Engineer"}
        # Clears the 5+ floor, over the 3-6 ceiling.
        assert await titles("years_experience=8") == {"Open Ended Engineer", "Unstated Engineer"}
        # Zero is a filter, not an absent one.
        assert await titles("years_experience=0") == {"Unstated Engineer"}
        # One decimal place, the scale the column stores.
        assert await titles("years_experience=5.5") == {
            "Open Ended Engineer",
            "Bounded Engineer",
            "Unstated Engineer",
        }

    async def test_rejects_an_impossible_years_value(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # A typo like 600 would otherwise return everything plus every unstated
        # job, and look like the filter is broken rather than the input.
        assert (
            await client.get(f"{API}/jobs?years_experience=-1", headers=auth_headers)
        ).status_code == 422
        assert (
            await client.get(f"{API}/jobs?years_experience=600", headers=auth_headers)
        ).status_code == 422

    async def test_list_rows_omit_the_description(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Twenty full postings to render a list of titles is hundreds of KB.
        await client.post(f"{API}/jobs", headers=auth_headers, json={"description": posting()})
        row = (await client.get(f"{API}/jobs", headers=auth_headers)).json()["items"][0]
        assert "description_raw" not in row
        assert row["skill_count"] > 0

    async def test_paginates(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        for index in range(3):
            await client.post(
                f"{API}/jobs",
                headers=auth_headers,
                json={"description": posting(title=f"Engineer {index}")},
            )

        page = await client.get(f"{API}/jobs?limit=2&offset=0", headers=auth_headers)
        assert page.json()["total"] == 3
        assert len(page.json()["items"]) == 2

    async def test_detail_returns_the_full_posting(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        created = (
            await client.post(f"{API}/jobs", headers=auth_headers, json={"description": posting()})
        ).json()["job"]

        detail = await client.get(f"{API}/jobs/{created['id']}", headers=auth_headers)
        assert detail.status_code == 200
        assert "Responsibilities" in detail.json()["description_raw"]
        # REQUIRED first: the reason to open a posting is to see what it demands.
        assert detail.json()["skills"][0]["requirement"] == "REQUIRED"

    async def test_unknown_job_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(f"{API}/jobs/{uuid.uuid4()}", headers=auth_headers)
        assert response.status_code == 404

    async def test_the_corpus_is_shared(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Unlike resumes, a job submitted by one user is visible to all: it is
        # market data everyone is ranked against.
        created = (
            await client.post(f"{API}/jobs", headers=auth_headers, json={"description": posting()})
        ).json()["job"]

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "other@example.com", "password": "correct-horse-9"},
        )
        other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.get(f"{API}/jobs/{created['id']}", headers=other_headers)
        assert response.status_code == 200


class TestImport:
    @pytest.fixture
    async def admin_headers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        registered_user: dict[str, object],
        user_payload: dict[str, str],
    ) -> dict[str, str]:
        await make_admin(db_session, user_payload["email"])
        tokens = registered_user["tokens"]  # type: ignore[index]
        return {"Authorization": f"Bearer {tokens['access_token']}"}  # type: ignore[index]

    def records(self) -> list[dict[str, str]]:
        return [
            {"external_id": "a1", "description": posting(title="Engineer A")},
            {"external_id": "a2", "description": posting(title="Engineer B")},
        ]

    async def test_imports_a_batch(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )

        assert response.status_code == 200, response.text
        assert response.json()["created"] == 2
        assert response.json()["failed"] == []

    async def test_re_running_the_same_batch_creates_nothing(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.3 AC1 — idempotency, keyed on (source, external_id)."""
        await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )
        again = await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )

        assert again.json()["created"] == 0
        assert again.json()["duplicates"] == 2

        listing = await client.get(f"{API}/jobs", headers=admin_headers)
        assert listing.json()["total"] == 2

    async def test_a_bad_record_does_not_abort_the_batch(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.3 AC2 — the whole point of a per-record report.

        Aborting on the first bad row makes a 10,000-record import unusable:
        nothing lands, and the operator has to bisect the file to find out why.
        """
        records = [
            {"external_id": "good-1", "description": posting(title="Engineer A")},
            {"external_id": "bad-1", "description": "too short to be a posting"},
            {"external_id": "good-2", "description": posting(title="Engineer B")},
        ]

        response = await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": records}
        )

        body = response.json()
        assert body["created"] == 2
        assert len(body["failed"]) == 1
        assert body["failed"][0]["external_id"] == "bad-1"
        assert body["failed"][0]["index"] == 1
        assert "too short" in body["failed"][0]["reason"].lower()
        assert body["processed"] == 3

    async def test_import_is_admin_only(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # 403, not 404: the caller already knows the endpoint exists.
        response = await client.post(
            f"{API}/admin/jobs/import", headers=auth_headers, json={"records": self.records()}
        )
        assert response.status_code == 403

    async def test_imported_jobs_record_their_source(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        # Provenance changes how much a row is trusted.
        await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )
        job = await db_session.scalar(select(Job).where(Job.external_id == "a1"))
        assert job is not None
        assert job.source.value == "DATASET_IMPORT"
