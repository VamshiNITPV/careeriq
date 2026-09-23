"""Which band a captured match score falls in (US-7.2 AC2)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.application.analytics import UNRECORDED, band_for


class TestBandFor:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (Decimal("0"), "Under 50"),
            (Decimal("49.99"), "Under 50"),
            # The edges, which is the only part of band arithmetic that is ever
            # wrong. Inclusive lower bound, matching the Jobs page filter this
            # borrows its numbers from: "60 and above" includes 60.
            (Decimal("50"), "50-59"),
            (Decimal("59.99"), "50-59"),
            (Decimal("60"), "60-69"),
            (Decimal("69.99"), "60-69"),
            (Decimal("70"), "70 and above"),
            (Decimal("100"), "70 and above"),
        ],
    )
    def test_the_boundaries_land_where_the_filter_says(
        self, score: Decimal, expected: str
    ) -> None:
        assert band_for(score) == expected

    def test_no_score_is_not_a_low_score(self) -> None:
        """An application sent before the snapshot existed has no score.

        That is not "under 50". Bucketing it as the worst band would invent a
        result for every application filed before migration 0020 and drag the
        table's worst row down with jobs nobody measured.
        """
        assert band_for(None) == UNRECORDED
