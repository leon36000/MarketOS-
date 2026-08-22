"""Deterministic replay of market snapshots and paper order intents."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

from .authoritative_books import DurableLedger
from .canonical import canonical_json, canonical_sha256
from .execution_safety import C13PreTradeEnvelope
from .errors import InvariantViolation
from .events import EventEnvelope, EventKind, sort_events
from .money import Money, Price, Quantity
from .orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
from .paper import ExecutionReport, MarketSnapshot, PaperBroker
from .portfolio import PortfolioSnapshot
from .risk import RiskKernel, RiskLimits
from .store import SQLiteEventStore, _decode
from .time import ClockQuality, EventTime


class ReplayStatus(str, Enum):
    COMPLETE = "COMPLETE"
    STOPPED_LIMIT = "STOPPED_LIMIT"


def _decimal(value: Decimal | str | int, code: str) -> Decimal:
    if isinstance(value, float):
        raise InvariantViolation("FLOAT_FORBIDDEN")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise InvariantViolation(code) from exc
    if not parsed.is_finite() or parsed < 0:
        raise InvariantViolation(code)
    return parsed


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_thaw(item) for item in value)
    return value


def _event_plain(event: EventEnvelope) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "kind": event.kind.value,
        "time": event.time.canonical_dict(),
        "source_id": event.source_id,
        "source_priority": event.source_priority,
        "source_sequence": event.source_sequence,
        "schema_version": event.schema_version,
        "payload": _thaw(event.payload),
    }


def _event_from_plain(data: Mapping[str, Any]) -> EventEnvelope:
    time = data["time"]
    return EventEnvelope(
        event_id=str(data["event_id"]),
        kind=EventKind(str(data["kind"])),
        time=EventTime(
            event_time_ns=int(time["event_time_ns"]),
            available_at_ns=int(time["available_at_ns"]),
            received_wall_ns=int(time["received_wall_ns"]),
            received_monotonic_ns=int(time["received_monotonic_ns"]),
        ),
        source_id=str(data["source_id"]),
        source_priority=int(data["source_priority"]),
        source_sequence=int(data["source_sequence"]),
        schema_version=str(data["schema_version"]),
        payload=dict(data["payload"]),
    )


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    run_id: str
    base_currency: str
    initial_cash: Money
    fee_bps: Decimal
    slippage_bps: Decimal
    max_events: int | None = None
    knowledge_cutoff_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise InvariantViolation("MISSING_REPLAY_RUN_ID")
        currency = self.base_currency.upper()
        if self.initial_cash.currency != currency or self.initial_cash.minor_units < 0:
            raise InvariantViolation("INVALID_REPLAY_INITIAL_CASH")
        object.__setattr__(self, "base_currency", currency)
        object.__setattr__(self, "fee_bps", _decimal(self.fee_bps, "INVALID_FEE_BPS"))
        object.__setattr__(self, "slippage_bps", _decimal(self.slippage_bps, "INVALID_SLIPPAGE_BPS"))
        if self.max_events is not None and (
            isinstance(self.max_events, bool) or not isinstance(self.max_events, int) or self.max_events <= 0
        ):
            raise InvariantViolation("INVALID_MAX_EVENTS")
        if self.knowledge_cutoff_ns is not None and (
            isinstance(self.knowledge_cutoff_ns, bool)
            or not isinstance(self.knowledge_cutoff_ns, int)
            or self.knowledge_cutoff_ns < 0
        ):
            raise InvariantViolation("INVALID_KNOWLEDGE_CUTOFF")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "base_currency": self.base_currency,
            "initial_cash": self.initial_cash,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "max_events": self.max_events,
            "knowledge_cutoff_ns": self.knowledge_cutoff_ns,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReplayCheckpoint:
    config_sha256: str
    risk_limits_sha256: str
    processed_events: tuple[EventEnvelope, ...]
    prefix_fingerprint: str

    def canonical_dict(self) -> dict[str, object]:
        return {
            "config_sha256": self.config_sha256,
            "risk_limits_sha256": self.risk_limits_sha256,
            "processed_events": tuple(_event_plain(event) for event in self.processed_events),
            "prefix_fingerprint": self.prefix_fingerprint,
        }

    def to_json(self) -> str:
        return canonical_json(self.canonical_dict())

    @classmethod
    def from_json(cls, text: str) -> "ReplayCheckpoint":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvariantViolation("INVALID_REPLAY_CHECKPOINT_JSON") from exc
        return cls(
            config_sha256=str(data["config_sha256"]),
            risk_limits_sha256=str(data["risk_limits_sha256"]),
            processed_events=tuple(_event_from_plain(item) for item in data["processed_events"]),
            prefix_fingerprint=str(data["prefix_fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: ReplayStatus
    events_processed: int
    reports: tuple[ExecutionReport, ...]
    portfolio: PortfolioSnapshot
    fingerprint: str
    live_trading_state: str = "HARD_LOCKED"


class ReplayEngine:
    def __init__(
        self,
        *,
        config: ReplayConfig,
        risk_limits: RiskLimits,
        store: SQLiteEventStore | None = None,
    ) -> None:
        if config.base_currency != risk_limits.currency:
            raise InvariantViolation("REPLAY_RISK_CURRENCY_MISMATCH")
        self.config = config
        self.risk_limits = risk_limits
        self.store = store

    def _new_runtime(self):
        runtime_dir = tempfile.TemporaryDirectory(prefix="marketos-replay-")
        ledger = DurableLedger(Path(runtime_dir.name) / "replay.sqlite")
        portfolio = ledger.authoritative_book(base_currency=self.config.base_currency)
        if self.config.initial_cash.minor_units:
            portfolio.fund(
                f"replay:{self.config.run_id}:fund",
                self.config.initial_cash,
                occurred_at_ns=0,
            )
        ledger.checkpoint(
            f"replay:{self.config.run_id}:initial",
            portfolio,
            captured_at_ns=0,
        )
        broker = PaperBroker(
            portfolio=portfolio,
            risk_kernel=RiskKernel(self.risk_limits),
            fee_bps=self.config.fee_bps,
            slippage_bps=self.config.slippage_bps,
        )
        envelope = C13PreTradeEnvelope(
            broker=broker,
            book=portfolio,
            ledger=ledger,
        )
        return runtime_dir, ledger, portfolio, broker, envelope

    @staticmethod
    def _market_from_event(event: EventEnvelope) -> MarketSnapshot:
        payload = event.payload
        currency = str(payload["currency"])
        tick_size = str(payload["tick_size"])
        return MarketSnapshot(
            instrument_id=str(payload["instrument_id"]),
            bid=Price.parse(currency, str(payload["bid"]), tick_size=tick_size),
            ask=Price.parse(currency, str(payload["ask"]), tick_size=tick_size),
            bid_size=Quantity.parse(str(payload["bid_size"])),
            ask_size=Quantity.parse(str(payload["ask_size"])),
            available_at_ns=event.time.available_at_ns,
            source_event_id=event.event_id,
        )

    @staticmethod
    def _intent_from_event(event: EventEnvelope) -> OrderIntent:
        payload = event.payload
        limit_raw = payload.get("limit_price")
        limit_price = None
        if limit_raw is not None:
            currency = str(payload.get("currency", "USD"))
            tick_size = str(payload.get("tick_size", "0.01"))
            limit_price = Price.parse(currency, str(limit_raw), tick_size=tick_size)
        return OrderIntent(
            intent_id=str(payload["intent_id"]),
            client_order_id=str(payload["client_order_id"]),
            idempotency_key=str(payload["idempotency_key"]),
            instrument_id=str(payload["instrument_id"]),
            side=OrderSide(str(payload["side"])),
            quantity=Quantity.positive(str(payload["quantity"])),
            order_type=OrderType(str(payload["order_type"])),
            limit_price=limit_price,
            time_in_force=TimeInForce(str(payload["time_in_force"])),
            created_at_ns=int(payload["created_at_ns"]),
            valid_from_ns=int(payload["valid_from_ns"]),
            expires_at_ns=int(payload["expires_at_ns"]),
            strategy_version=str(payload["strategy_version"]),
            config_sha256=str(payload["config_sha256"]),
            mode=ExecutionMode(str(payload.get("mode", "PAPER"))),
        )

    def _validate_cutoff(self, ordered: tuple[EventEnvelope, ...]) -> None:
        cutoff = self.config.knowledge_cutoff_ns
        if cutoff is None:
            return
        for event in ordered:
            if event.time.available_at_ns > cutoff:
                raise InvariantViolation(f"EVENT_AFTER_KNOWLEDGE_CUTOFF:{event.event_id}")

    def _run_ordered(
        self,
        ordered: tuple[EventEnvelope, ...],
        *,
        ignore_max_events: bool = False,
    ) -> ReplayResult:
        self._validate_cutoff(ordered)
        runtime_dir, ledger, portfolio, broker, envelope = self._new_runtime()
        reports: list[ExecutionReport] = []
        try:
            limit = None if ignore_max_events else self.config.max_events
            process_count = len(ordered) if limit is None else min(len(ordered), limit)

            for event in ordered[:process_count]:
                if self.store is not None:
                    self.store.append(event)
                if event.kind is EventKind.MARKET_SNAPSHOT:
                    broker.update_market(self._market_from_event(event))
                elif event.kind is EventKind.ORDER_INTENT:
                    report = envelope.submit(
                        self._intent_from_event(event),
                        now_ns=event.time.available_at_ns,
                        clock_quality=ClockQuality(
                            source="replay",
                            synchronization_method="DETERMINISTIC",
                            last_sync_wall_ns=event.time.available_at_ns,
                            max_error_ns=0,
                            offset_ns=0,
                            quality_state="SYNCED",
                        ),
                    )
                    reports.append(report)
                    if self.store is not None:
                        evidence_payload = _decode(
                            json.loads(canonical_json(report.canonical_dict()))
                        )
                        self.store.append_evidence("EXECUTION_REPORT", evidence_payload)
                else:
                    raise InvariantViolation(f"UNSUPPORTED_REPLAY_EVENT_KIND:{event.kind.value}")

            status = ReplayStatus.STOPPED_LIMIT if process_count < len(ordered) else ReplayStatus.COMPLETE
            snapshot = portfolio.snapshot()
            fingerprint = canonical_sha256(
                {
                    "config": self.config,
                    "risk_limits": self.risk_limits,
                    "event_sha256": tuple(event.sha256() for event in ordered[:process_count]),
                    "reports": tuple(report.canonical_dict() for report in reports),
                    "portfolio": snapshot,
                    "status": status,
                    "events_processed": process_count,
                    "live_trading_state": "HARD_LOCKED",
                }
            )
            return ReplayResult(
                status=status,
                events_processed=process_count,
                reports=tuple(reports),
                portfolio=snapshot,
                fingerprint=fingerprint,
            )
        finally:
            ledger.close()
            runtime_dir.cleanup()

    def run(self, events: Iterable[EventEnvelope]) -> ReplayResult:
        return self._run_ordered(sort_events(events))

    def checkpoint(self, events: Iterable[EventEnvelope], *, after_events: int) -> ReplayCheckpoint:
        ordered = sort_events(events)
        if isinstance(after_events, bool) or not isinstance(after_events, int) or not 0 <= after_events <= len(ordered):
            raise InvariantViolation("INVALID_CHECKPOINT_POSITION")
        prefix = ordered[:after_events]
        result = self._run_ordered(prefix, ignore_max_events=True)
        return ReplayCheckpoint(
            config_sha256=self.config.sha256(),
            risk_limits_sha256=self.risk_limits.sha256(),
            processed_events=prefix,
            prefix_fingerprint=result.fingerprint,
        )

    def resume(
        self,
        checkpoint: ReplayCheckpoint,
        remaining_events: Iterable[EventEnvelope],
    ) -> ReplayResult:
        if checkpoint.config_sha256 != self.config.sha256():
            raise InvariantViolation("CHECKPOINT_CONFIG_MISMATCH")
        if checkpoint.risk_limits_sha256 != self.risk_limits.sha256():
            raise InvariantViolation("CHECKPOINT_RISK_MISMATCH")
        prefix_result = self._run_ordered(checkpoint.processed_events, ignore_max_events=True)
        if prefix_result.fingerprint != checkpoint.prefix_fingerprint:
            raise InvariantViolation("CHECKPOINT_PREFIX_FINGERPRINT_MISMATCH")
        combined = tuple(checkpoint.processed_events) + tuple(remaining_events)
        return self.run(combined)
