"""Which question the scheduler asks next.

Pure functions over a dict, so no database here. What matters is the two claims
the rotation makes: that it never repeats while anything is unasked, and that
once everything has been asked it returns to the oldest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.job.rotation import (
    DEFAULT_LOCATIONS,
    ROLE_GROUPS,
    build_queries,
    next_query,
)


class TestBuildQueries:
    def test_covers_every_group_and_location_once(self) -> None:
        queries = build_queries()

        assert len(queries) == len(ROLE_GROUPS) * len(DEFAULT_LOCATIONS)
        assert len(set(queries)) == len(queries)

    def test_a_day_of_requests_covers_every_role(self) -> None:
        """The whole reason the roles are grouped.

        Six groups is one city's worth of questions, so six requests — a day's
        budget — ask about every role name on the list. Ungrouped it was
        nineteen roles crawling one at a time, and a role at the end of the
        list waited three weeks for its first look.
        """
        per_day = len(ROLE_GROUPS)
        first_day = build_queries()[:per_day]

        named = " ".join(first_day)
        for group in ROLE_GROUPS:
            for role in group:
                assert role in named

    def test_asks_about_a_whole_group_in_one_query(self) -> None:
        """OR between the terms, which the provider honours — see the module docstring."""
        queries = build_queries(groups=(("alpha", "beta"),), locations=("Pune",))

        assert queries == ["alpha OR beta in Pune"]

    def test_keeps_a_rare_term_out_of_a_group(self) -> None:
        """Measured: "vibe coder" returns nothing when grouped with "ai engineer".

        The common terms take all ten result slots, so a rare one only ever
        surfaces as a question of its own.
        """
        solo = [group for group in ROLE_GROUPS if len(group) == 1]

        assert ("vibe coder",) in solo

    def test_finishes_a_city_before_moving_to_the_next(self) -> None:
        """City-major, which is the opposite of what it was — and deliberate.

        Six groups is exactly one city, so this ordering means each day covers
        every role in one city and the next day moves on. The full matrix comes
        round in nine days rather than twenty-eight, so a repeat is asked of an
        index that has had a week to change rather than a month.
        """
        queries = build_queries(groups=(("python",), ("java",)), locations=("Pune", "Chennai"))

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
        candidates = build_queries(groups=(("a",), ("b",)), locations=("X", "Y", "Z"))
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
