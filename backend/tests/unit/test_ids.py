"""Tests for UUIDv7 generation.

These matter more than they look: every primary key in the system comes from
here, and a bug in the bit layout would produce UUIDs that are valid-looking but
not sortable — which is the entire reason for choosing v7 over v4.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.core.ids import uuid7, uuid7_timestamp_ms


class TestUuid7Format:
    def test_returns_uuid_instance(self) -> None:
        assert isinstance(uuid7(), uuid.UUID)

    def test_version_is_7(self) -> None:
        assert uuid7().version == 7

    def test_variant_is_rfc_4122(self) -> None:
        # Bits 63..62 must be 0b10. A wrong variant makes the value a
        # non-conforming UUID that some databases and libraries will reject.
        assert (uuid7().int >> 62) & 0b11 == 0b10

    def test_string_form_is_canonical(self) -> None:
        s = str(uuid7())
        assert len(s) == 36
        assert s[14] == "7"  # version nibble sits at this position


class TestUuid7Uniqueness:
    def test_no_collisions_in_a_large_batch(self) -> None:
        # 74 random bits per value; a collision here means the RNG is not wired
        # up, not bad luck.
        values = {uuid7() for _ in range(10_000)}
        assert len(values) == 10_000


class TestUuid7Ordering:
    def test_values_sort_by_creation_time(self) -> None:
        """The property that justifies choosing v7 (architecture.md section 4)."""
        first = uuid7()
        time.sleep(0.002)
        second = uuid7()
        time.sleep(0.002)
        third = uuid7()

        assert first < second < third
        assert sorted([third, first, second]) == [first, second, third]

    def test_string_sort_matches_value_sort(self) -> None:
        # Postgres orders the uuid type by value, but logs and exports are often
        # sorted as text. Hex encoding preserves order, so both agree.
        values = []
        for _ in range(5):
            values.append(uuid7())
            time.sleep(0.002)

        assert [str(v) for v in sorted(values)] == sorted(str(v) for v in values)


class TestUuid7Timestamp:
    def test_embedded_timestamp_matches_generation_time(self) -> None:
        before = time.time_ns() // 1_000_000
        value = uuid7()
        after = time.time_ns() // 1_000_000

        assert before <= uuid7_timestamp_ms(value) <= after

    def test_rejects_non_v7_uuid(self) -> None:
        # The high bits of a v4 are random, so returning a "timestamp" for one
        # would be a silently meaningless number.
        with pytest.raises(ValueError, match="Expected a UUIDv7"):
            uuid7_timestamp_ms(uuid.uuid4())
