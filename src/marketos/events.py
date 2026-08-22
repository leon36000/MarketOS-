"""Immutable event envelope and deterministic total ordering."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .time import EventTime


class EventKind(str, Enum):
    SYSTEM = "SYSTEM"
    MARKET_SNAPSHOT = "MARKET_SNAPSHOT"
    REFERENCE_UPDATE = "REFERENCE_UPDATE"
    ORDER_INTENT = "ORDER_INTENT"
    RISK_DECISION = "RISK_DECISION"
    FILL = "FILL"
    LEDGER_ENTRY = "LEDGER_ENTRY"
    CHECKPOINT = "CHECKPOINT"


_KIND_PRIORITY: dict[EventKind, int] = {
    EventKind.SYSTEM: 0,
    EventKind.REFERENCE_UPDATE: 10,
    EventKind.MARKET_SNAPSHOT: 20,
    EventKind.ORDER_INTENT: 30,
    EventKind.RISK_DECISION: 40,
    EventKind.FILL: 50,
    EventKind.LEDGER_ENTRY: 60,
    EventKind.CHECKPOINT: 70,
}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    kind: EventKind
    time: EventTime
    source_id: str
    source_priority: int
    source_sequence: int
    schema_version: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise InvariantViolation("MISSING_EVENT_ID")
        if not isinstance(self.kind, EventKind):
            raise InvariantViolation("INVALID_EVENT_KIND")
        if not self.source_id.strip():
            raise InvariantViolation("MISSING_SOURCE_ID")
        for value, code in (
            (self.source_priority, "NEGATIVE_SOURCE_PRIORITY"),
            (self.source_sequence, "NEGATIVE_SOURCE_SEQUENCE"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvariantViolation(code)
        if not self.schema_version.strip():
            raise InvariantViolation("MISSING_SCHEMA_VERSION")
        if not isinstance(self.payload, Mapping):
            raise InvariantViolation("EVENT_PAYLOAD_MUST_BE_MAPPING")
        frozen = _freeze(dict(self.payload))
        canonical_sha256(frozen)
        object.__setattr__(self, "payload", frozen)

    def sort_key(self) -> tuple[int, int, int, int, int, str]:
        return (
            self.time.available_at_ns,
            self.source_priority,
            self.source_sequence,
            self.time.event_time_ns,
            _KIND_PRIORITY[self.kind],
            self.event_id,
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "time": self.time,
            "source_id": self.source_id,
            "source_priority": self.source_priority,
            "source_sequence": self.source_sequence,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


def sort_events(events: Iterable[EventEnvelope]) -> tuple[EventEnvelope, ...]:
    materialized = tuple(events)
    ids = [event.event_id for event in materialized]
    if len(ids) != len(set(ids)):
        raise InvariantViolation("DUPLICATE_EVENT_ID_IN_REPLAY_INPUT")
    return tuple(sorted(materialized, key=EventEnvelope.sort_key))
