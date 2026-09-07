"""Which question the scheduler asks next.

Pure functions over a dict, so no database here. What matters is the two claims
the rotation makes: that it never repeats while anything is unasked, and that
once everything has been asked it returns to the oldest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.job.rotation import (
    DEFAULT_LOCATIONS,
    DEFAULT_ROLES,
    PRIORITY_ROLES,
    build_queries,
    next_query,
)


class TestBuildQueries:
    def test_covers_every_role_and_location_once(self) -> None:
        queries = build_queries()
        roles = len(DEFAULT_ROLES) + len(PRIORITY_ROLES)

        assert len(queries) == roles * len(DEFAULT_LOCATIONS)
        assert len(set(queries)) == len(queries)

    def test_priority_roles_reach_every_city_before_anything_else(self) -> None:
        """The point of the priority block, and the reason it is not just an ordering.

        Putting a role at the top of `DEFAULT_ROLES` would fetch it in the first
        city on day one and in the ninth city a month later, because the
        rotation is location-major. Crossing it with every city up front is what
        actually makes the whole group arrive early.
        """
        queries = build_queries(
            roles=("established",), locations=("X", "Y"), priority_roles=("urgent",)
        )

        assert queries == [
            "urgent in X",
            "urgent in Y",
            "established in X",
            "established in Y",
        ]

    def test_a_role_named_twice_is_asked_once(self) -> None:
        """A maintenance slip, not a reason to fail — but never a wasted request."""
        queries = build_queries(
            roles=("python developer",),
            locations=("Pune",),
            priority_roles=("python developer",),
        )

        assert queries == ["python developer in Pune"]

    def test_consecutive_queries_span_cities_not_one_city(self) -> None:
        """Location-major ordering, so a day's six fetches cover six cities.

        Role-major would spend the first fortnight on Bengaluru alone.
        """
        queries = build_queries(
            roles=("python", "java"), locations=("Pune", "Chennai"), priority_roles=()
        )

        assert queries == [
            "python in Pune",
            "java in Pune",
            "python in Chennai",
            "java in Chennai",
        ]


class TestNextQuery:
    def test_prefers_a_query_never_asked(self) -> None:
        now = datetime.now(UTC)
        # "a" was asked seconds ago, "b" never. Recency alone would pick "a".
        candidates = ["a", "b"]

        assert next_query(candidates, {"a": now}) == "b"

    def test_unasked_wins_even_against_the_oldest_asked(self) -> None:
        """The ordering is unused-first, then least-recently-used — not one scale.

        A query asked a year ago is still a question with a known answer; an
        unasked one is the only kind guaranteed to return jobs the corpus does
        not already have.
        """
        ancient = datetime.now(UTC) - timedelta(days=300)

        assert next_query(["asked", "never"], {"asked": ancient}) == "never"

    def test_falls_back_to_the_oldest_once_all_have_been_asked(self) -> None:
        now = datetime.now(UTC)
        last_used = {
            "recent": now,
            "oldest": now - timedelta(days=10),
            "middle": now - timedelta(days=2),
        }

        assert next_query(list(last_used), last_used) == "oldest"

    def test_returns_none_only_when_there_is_nothing_to_ask(self) -> None:
        assert next_query([], {}) is None

    def test_rotation_visits_everything_before_repeating(self) -> None:
        """The property that makes the corpus grow, simulated over a full cycle."""
        candidates = build_queries(roles=("a", "b"), locations=("X", "Y", "Z"))
        last_used: dict[str, datetime] = {}
        now = datetime.now(UTC)
        picked: list[str] = []

        for minute in range(len(candidates)):
            query = next_query(candidates, last_used)
            assert query is not None
            picked.append(query)
            last_used[query] = now + timedelta(minutes=minute)

        assert sorted(picked) == sorted(candidates)
        # And the next one round is the one asked first, not a fresh repeat of
        # the one just asked.
        assert next_query(candidates, last_used) == picked[0]
