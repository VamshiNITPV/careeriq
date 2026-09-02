"""UUIDv7 generation.

Architecture.md §4 specifies UUIDv7 primary keys everywhere. Sequential integers
leak record counts and make resource enumeration trivial; UUIDv4 solves that but
is randomly distributed, so every insert lands in a random position in the
B-tree, fragmenting the index and thrashing cache. UUIDv7 embeds a millisecond
timestamp in the high bits, so values generated near in time sort near each
other and inserts stay local.

Python's stdlib gained uuid7 in 3.14; this project targets 3.13, so it is
implemented here. Roughly 20 lines is cheaper than a dependency, and it is
directly unit-testable.

Layout (RFC 9562 §5.7), 128 bits total:

    ┌──────────────────┬─────────┬────────────┬──────────┬────────────┐
    │ unix_ts_ms (48)  │ ver (4) │ rand_a (12)│ var (2)  │ rand_b (62)│
    └──────────────────┴─────────┴────────────┴──────────┴────────────┘
     bits 127..80       79..76    75..64       63..62     61..0
"""

from __future__ import annotations

import secrets
import time
import uuid

_VERSION = 0x7
_VARIANT = 0b10


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUIDv7."""
    timestamp_ms = time.time_ns() // 1_000_000

    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= _VERSION << 76
    value |= secrets.randbits(12) << 64
    value |= _VARIANT << 62
    value |= secrets.randbits(62)

    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Extract the embedded creation timestamp in milliseconds since the epoch.

    Useful for debugging and for asserting ordering in tests. Raises if the UUID
    is not version 7, since the high bits of other versions are not a timestamp
    and would silently return a meaningless number.
    """
    if value.version != 7:
        raise ValueError(f"Expected a UUIDv7, got version {value.version}")
    return value.int >> 80
