"""Clock quality and multi-time event contracts."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import InvariantViolation


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvariantViolation(code)
    if value < 0:
        raise InvariantViolation(code)
    return value


@dataclass(frozen=True, slots=True)
class ClockQuality:
    source: str
    synchronization_method: str
    last_sync_wall_ns: int
    max_error_ns: int
    offset_ns: int
    quality_state: str

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.synchronization_method.strip():
            raise InvariantViolation("MISSING_CLOCK_SOURCE")
        _nonnegative_int(self.last_sync_wall_ns, "NEGATIVE_CLOCK_SYNC_TIME")
        _nonnegative_int(self.max_error_ns, "NEGATIVE_CLOCK_ERROR")
        if isinstance(self.offset_ns, bool) or not isinstance(self.offset_ns, int):
            raise InvariantViolation("INVALID_CLOCK_OFFSET")
        if self.quality_state not in {"SYNCED", "DEGRADED", "UNSYNCED", "UNKNOWN"}:
            raise InvariantViolation("INVALID_CLOCK_QUALITY_STATE")

    def is_acceptable(self, *, now_wall_ns: int, max_age_ns: int, max_error_ns: int) -> bool:
        _nonnegative_int(now_wall_ns, "NEGATIVE_WALL_TIME")
        _nonnegative_int(max_age_ns, "NEGATIVE_MAX_AGE")
        _nonnegative_int(max_error_ns, "NEGATIVE_MAX_ERROR")
        if self.quality_state != "SYNCED":
            return False
        if now_wall_ns < self.last_sync_wall_ns:
            return False
        return (
            now_wall_ns - self.last_sync_wall_ns <= max_age_ns
            and self.max_error_ns <= max_error_ns
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "synchronization_method": self.synchronization_method,
            "last_sync_wall_ns": self.last_sync_wall_ns,
            "max_error_ns": self.max_error_ns,
            "offset_ns": self.offset_ns,
            "quality_state": self.quality_state,
        }


@dataclass(frozen=True, slots=True)
class EventTime:
    event_time_ns: int
    available_at_ns: int
    received_wall_ns: int
    received_monotonic_ns: int

    def __post_init__(self) -> None:
        _nonnegative_int(self.event_time_ns, "NEGATIVE_EVENT_TIME")
        _nonnegative_int(self.available_at_ns, "NEGATIVE_AVAILABLE_TIME")
        _nonnegative_int(self.received_wall_ns, "NEGATIVE_RECEIVED_WALL_TIME")
        _nonnegative_int(self.received_monotonic_ns, "NEGATIVE_MONOTONIC_TIME")
        if self.available_at_ns < self.event_time_ns:
            raise InvariantViolation("LOOKAHEAD_EVENT_TIME")
        if self.available_at_ns < self.received_wall_ns:
            raise InvariantViolation("AVAILABLE_BEFORE_RECEIVE")

    def canonical_dict(self) -> dict[str, int]:
        return {
            "event_time_ns": self.event_time_ns,
            "available_at_ns": self.available_at_ns,
            "received_wall_ns": self.received_wall_ns,
            "received_monotonic_ns": self.received_monotonic_ns,
        }
