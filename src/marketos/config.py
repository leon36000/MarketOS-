"""Strict JSON configuration and scenario loaders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .errors import InvariantViolation
from .events import EventEnvelope, EventKind
from .money import Money, Quantity
from .risk import RiskLimits
from .time import EventTime


def _reject_float(token: str) -> None:
    raise InvariantViolation(f"FLOAT_TOKEN_FORBIDDEN:{token}")


def _reject_constant(token: str) -> None:
    raise InvariantViolation(f"NON_FINITE_TOKEN_FORBIDDEN:{token}")


def loads_strict_json(text: str) -> Any:
    try:
        return json.loads(text, parse_float=_reject_float, parse_constant=_reject_constant)
    except InvariantViolation:
        raise
    except json.JSONDecodeError as exc:
        raise InvariantViolation(f"INVALID_JSON:{exc.msg}") from exc


def load_json(path: str | Path) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise InvariantViolation(f"CONFIG_READ_ERROR:{path}") from exc
    return loads_strict_json(text)


def _require_mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvariantViolation(code)
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], code: str) -> None:
    actual = set(value)
    if actual != expected:
        raise InvariantViolation(f"{code}:missing={sorted(expected-actual)}:extra={sorted(actual-expected)}")


def load_risk_limits(path: str | Path) -> RiskLimits:
    data = _require_mapping(load_json(path), "RISK_CONFIG_MUST_BE_OBJECT")
    expected = {
        "currency",
        "allowed_instruments",
        "max_order_notional",
        "max_gross_notional",
        "max_position_quantity",
        "max_data_age_ns",
        "max_clock_sync_age_ns",
        "max_clock_error_ns",
        "allow_short",
    }
    _exact_keys(data, expected, "RISK_CONFIG_KEYS")
    instruments = data["allowed_instruments"]
    if not isinstance(instruments, list) or not all(isinstance(item, str) and item.strip() for item in instruments):
        raise InvariantViolation("INVALID_INSTRUMENT_ALLOWLIST")
    if len(instruments) != len(set(instruments)):
        raise InvariantViolation("DUPLICATE_INSTRUMENT_ALLOWLIST")
    for field in ("max_data_age_ns", "max_clock_sync_age_ns", "max_clock_error_ns"):
        if isinstance(data[field], bool) or not isinstance(data[field], int):
            raise InvariantViolation(f"{field.upper()}_MUST_BE_INT")
    if not isinstance(data["allow_short"], bool):
        raise InvariantViolation("ALLOW_SHORT_MUST_BE_BOOL")
    currency = str(data["currency"])
    return RiskLimits(
        currency=currency,
        allowed_instruments=frozenset(instruments),
        max_order_notional=Money.from_decimal(currency, data["max_order_notional"]),
        max_gross_notional=Money.from_decimal(currency, data["max_gross_notional"]),
        max_position_quantity=Quantity.positive(data["max_position_quantity"]),
        max_data_age_ns=data["max_data_age_ns"],
        max_clock_sync_age_ns=data["max_clock_sync_age_ns"],
        max_clock_error_ns=data["max_clock_error_ns"],
        allow_short=data["allow_short"],
    )


def event_from_mapping(data: Mapping[str, Any]) -> EventEnvelope:
    expected = {
        "event_id",
        "kind",
        "time",
        "source_id",
        "source_priority",
        "source_sequence",
        "schema_version",
        "payload",
    }
    _exact_keys(data, expected, "EVENT_KEYS")
    time = _require_mapping(data["time"], "EVENT_TIME_MUST_BE_OBJECT")
    _exact_keys(
        time,
        {"event_time_ns", "available_at_ns", "received_wall_ns", "received_monotonic_ns"},
        "EVENT_TIME_KEYS",
    )
    payload = _require_mapping(data["payload"], "EVENT_PAYLOAD_MUST_BE_OBJECT")
    return EventEnvelope(
        event_id=str(data["event_id"]),
        kind=EventKind(str(data["kind"])),
        time=EventTime(
            event_time_ns=time["event_time_ns"],
            available_at_ns=time["available_at_ns"],
            received_wall_ns=time["received_wall_ns"],
            received_monotonic_ns=time["received_monotonic_ns"],
        ),
        source_id=str(data["source_id"]),
        source_priority=data["source_priority"],
        source_sequence=data["source_sequence"],
        schema_version=str(data["schema_version"]),
        payload=dict(payload),
    )


def load_events_jsonl(path: str | Path) -> tuple[EventEnvelope, ...]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InvariantViolation(f"SCENARIO_READ_ERROR:{path}") from exc
    events: list[EventEnvelope] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = _require_mapping(loads_strict_json(line), "EVENT_LINE_MUST_BE_OBJECT")
            events.append(event_from_mapping(data))
        except Exception as exc:
            if isinstance(exc, InvariantViolation):
                raise InvariantViolation(f"SCENARIO_LINE_{line_number}:{exc}") from exc
            raise
    if not events:
        raise InvariantViolation("EMPTY_SCENARIO")
    return tuple(events)
