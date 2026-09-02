"""External provider adapters, each behind an interface (ADR-007).

Business logic depends on the protocol, never on a vendor SDK. That keeps
services testable offline and makes swapping a provider a config change.
"""
