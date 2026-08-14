"""Immutable execution evidence and observed-truth firewall.

Paper, replay, synthetic and counterfactual outcomes remain useful research
artifacts, but only explicitly broker-observed evidence enters the observed
truth view.  Every record is tied to content-addressed raw evidence and is
verified on append, read and idempotent redelivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping
from uuid import UUID

from .canonical import canonical_json, canonical_sha256
from .datafabric import RawEvidenceStore
from .errors import DuplicateConflict, InvariantViolation
from .money import Money, Price, Quantity
from .orders import OrderSide, OrderType

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _positive_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvariantViolation(code)
    return value


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _decode_canonical(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_canonical(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(str(value["$decimal"]))
        if set(value) == {"$uuid"}:
            return UUID(str(value["$uuid"]))
        return {str(key): _decode_canonical(item) for key, item in value.items()}
    return value


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvariantViolation(code)
    return value


class EvidenceOrigin(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    PAPER = "PAPER"
    SHADOW_COUNTERFACTUAL = "SHADOW_COUNTERFACTUAL"
    BROKER_OBSERVED = "BROKER_OBSERVED"


class Marketability(str, Enum):
    MARKETABLE = "MARKETABLE"
    NON_MARKETABLE = "NON_MARKETABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    instrument_id: str
    venue_id: UUID
    order_type: OrderType
    side: OrderSide
    marketability: Marketability
    size_bucket: str
    regime: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _text(self.instrument_id, "MISSING_EXECUTION_INSTRUMENT_ID").upper(),
        )
        if not isinstance(self.venue_id, UUID):
            raise InvariantViolation("INVALID_EXECUTION_VENUE_ID")
        if not isinstance(self.order_type, OrderType):
            raise InvariantViolation("INVALID_EXECUTION_ORDER_TYPE")
        if not isinstance(self.side, OrderSide):
            raise InvariantViolation("INVALID_EXECUTION_SIDE")
        if not isinstance(self.marketability, Marketability):
            raise InvariantViolation("INVALID_EXECUTION_MARKETABILITY")
        object.__setattr__(
            self,
            "size_bucket",
            _text(self.size_bucket, "MISSING_EXECUTION_SIZE_BUCKET").upper(),
        )
        object.__setattr__(
            self,
            "regime",
            _text(self.regime, "MISSING_EXECUTION_REGIME").upper(),
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "venue_id": self.venue_id,
            "order_type": self.order_type,
            "side": self.side,
            "marketability": self.marketability,
            "size_bucket": self.size_bucket,
            "regime": self.regime,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    outcome_id: str
    version: int
    order_id: str
    context: ExecutionContext
    origin: EvidenceOrigin
    source_id: str
    external_execution_id: str | None
    raw_content_sha256: str
    submitted_quantity: Quantity
    filled_quantity: Quantity
    arrival_price: Price
    average_fill_price: Price | None
    fee: Money
    financing: Money
    opportunity_cost: Money
    submitted_at_ns: int
    acknowledged_at_ns: int
    completed_at_ns: int
    cancelled: bool
    rejected: bool
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outcome_id",
            _text(self.outcome_id, "MISSING_EXECUTION_OUTCOME_ID"),
        )
        _positive_int(self.version, "INVALID_EXECUTION_OUTCOME_VERSION")
        object.__setattr__(
            self,
            "order_id",
            _text(self.order_id, "MISSING_EXECUTION_ORDER_ID"),
        )
        if not isinstance(self.context, ExecutionContext):
            raise InvariantViolation("INVALID_EXECUTION_CONTEXT")
        if not isinstance(self.origin, EvidenceOrigin):
            raise InvariantViolation("INVALID_EXECUTION_EVIDENCE_ORIGIN")
        object.__setattr__(
            self,
            "source_id",
            _text(self.source_id, "MISSING_EXECUTION_SOURCE_ID"),
        )
        external_id = self.external_execution_id
        if self.origin is EvidenceOrigin.BROKER_OBSERVED:
            if external_id is None or not isinstance(external_id, str) or not external_id.strip():
                raise InvariantViolation(
                    "BROKER_OBSERVED_EXTERNAL_ID_REQUIRED"
                )
            object.__setattr__(self, "external_execution_id", external_id.strip())
        elif external_id is not None:
            raise InvariantViolation(
                "NON_BROKER_EXTERNAL_EXECUTION_ID_FORBIDDEN"
            )
        if (
            not isinstance(self.raw_content_sha256, str)
            or not _HEX64.fullmatch(self.raw_content_sha256)
        ):
            raise InvariantViolation("INVALID_EXECUTION_RAW_CONTENT_SHA256")
        if not isinstance(self.submitted_quantity, Quantity):
            raise InvariantViolation("INVALID_SUBMITTED_QUANTITY")
        if not isinstance(self.filled_quantity, Quantity):
            raise InvariantViolation("INVALID_FILLED_QUANTITY")
        if self.submitted_quantity.value <= 0:
            raise InvariantViolation("POSITIVE_SUBMITTED_QUANTITY_REQUIRED")
        if self.filled_quantity.value > self.submitted_quantity.value:
            raise InvariantViolation("FILLED_QUANTITY_EXCEEDS_SUBMITTED")
        if not isinstance(self.arrival_price, Price):
            raise InvariantViolation("INVALID_ARRIVAL_PRICE")
        if self.filled_quantity.value > 0 and self.average_fill_price is None:
            raise InvariantViolation("FILL_PRICE_REQUIRED")
        if self.filled_quantity.value == 0 and self.average_fill_price is not None:
            raise InvariantViolation("UNFILLED_PRICE_FORBIDDEN")
        if self.average_fill_price is not None:
            if not isinstance(self.average_fill_price, Price):
                raise InvariantViolation("INVALID_AVERAGE_FILL_PRICE")
            if (
                self.average_fill_price.currency != self.arrival_price.currency
                or self.average_fill_price.tick_size != self.arrival_price.tick_size
            ):
                raise InvariantViolation("EXECUTION_CURRENCY_MISMATCH")
        for amount in (self.fee, self.financing, self.opportunity_cost):
            if not isinstance(amount, Money):
                raise InvariantViolation("INVALID_EXECUTION_COST")
            if (
                amount.currency != self.arrival_price.currency
                or amount.minor_units < 0
            ):
                raise InvariantViolation("EXECUTION_CURRENCY_MISMATCH")
        _nonnegative_int(self.submitted_at_ns, "INVALID_EXECUTION_SUBMIT_TIME")
        _nonnegative_int(
            self.acknowledged_at_ns,
            "INVALID_EXECUTION_ACK_TIME",
        )
        _nonnegative_int(
            self.completed_at_ns,
            "INVALID_EXECUTION_COMPLETE_TIME",
        )
        if not (
            self.submitted_at_ns
            <= self.acknowledged_at_ns
            <= self.completed_at_ns
        ):
            raise InvariantViolation("EXECUTION_TIME_ORDER")
        if not isinstance(self.cancelled, bool) or not isinstance(self.rejected, bool):
            raise InvariantViolation("INVALID_EXECUTION_TERMINAL_STATE")
        if self.cancelled and self.rejected:
            raise InvariantViolation("OUTCOME_CANNOT_CANCEL_AND_REJECT")
        if self.rejected and self.filled_quantity.value > 0:
            raise InvariantViolation("REJECTED_OUTCOME_CANNOT_FILL")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("EXECUTION_EVIDENCE_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation(
                "EXECUTION_EVIDENCE_CANNOT_PROVE_PROFITABILITY"
            )

    @property
    def is_observed_truth(self) -> bool:
        return self.origin is EvidenceOrigin.BROKER_OBSERVED

    @property
    def fill_ratio(self) -> Decimal:
        return self.filled_quantity.value / self.submitted_quantity.value

    @property
    def ack_latency_ns(self) -> int:
        return self.acknowledged_at_ns - self.submitted_at_ns

    @property
    def completion_latency_ns(self) -> int:
        return self.completed_at_ns - self.submitted_at_ns

    @property
    def implementation_shortfall_bps(self) -> Decimal | None:
        if self.average_fill_price is None:
            return None
        arrival = self.arrival_price.value
        if arrival == 0:
            raise InvariantViolation("ZERO_ARRIVAL_PRICE")
        signed_difference = (
            self.average_fill_price.value - arrival
            if self.context.side is OrderSide.BUY
            else arrival - self.average_fill_price.value
        )
        return (
            signed_difference / arrival * Decimal("10000")
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)

    @property
    def total_explicit_cost(self) -> Money:
        return self.fee + self.financing + self.opportunity_cost

    def identity_tuple(self) -> tuple[object, ...]:
        return (
            self.outcome_id,
            self.order_id,
            self.context.sha256(),
            self.origin,
            self.source_id,
            self.external_execution_id,
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "outcome_id": self.outcome_id,
            "version": self.version,
            "order_id": self.order_id,
            "context": self.context,
            "origin": self.origin,
            "source_id": self.source_id,
            "external_execution_id": self.external_execution_id,
            "raw_content_sha256": self.raw_content_sha256,
            "submitted_quantity": self.submitted_quantity,
            "filled_quantity": self.filled_quantity,
            "arrival_price": self.arrival_price,
            "average_fill_price": self.average_fill_price,
            "fee": self.fee,
            "financing": self.financing,
            "opportunity_cost": self.opportunity_cost,
            "submitted_at_ns": self.submitted_at_ns,
            "acknowledged_at_ns": self.acknowledged_at_ns,
            "completed_at_ns": self.completed_at_ns,
            "cancelled": self.cancelled,
            "rejected": self.rejected,
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class ExecutionEvidenceLedger:
    """Append-only execution evidence with a broker-observed truth view."""

    live_trading_state = "HARD_LOCKED"
    profitability_state = "UNPROVEN"
    broker_selected = False
    observed_broker_feed_qualified = False
    execution_simulator_calibrated = False

    def __init__(
        self,
        path: str | Path,
        *,
        raw_evidence_store: RawEvidenceStore,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_evidence_store = raw_evidence_store
        self._closed = False
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS execution_outcomes (
                ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                outcome_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                origin TEXT NOT NULL,
                context_sha256 TEXT NOT NULL,
                identity_sha256 TEXT NOT NULL,
                raw_content_sha256 TEXT NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                UNIQUE(outcome_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_execution_origin
                ON execution_outcomes(origin, ledger_sequence);
            CREATE TRIGGER IF NOT EXISTS execution_outcomes_no_update
            BEFORE UPDATE ON execution_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_EXECUTION_EVIDENCE');
            END;
            CREATE TRIGGER IF NOT EXISTS execution_outcomes_no_delete
            BEFORE DELETE ON execution_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_EXECUTION_EVIDENCE');
            END;
            """
        )

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def __enter__(self) -> "ExecutionEvidenceLedger":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _verify_raw(self, content_sha256: str) -> None:
        if not self.raw_evidence_store.verify(content_sha256):
            raise InvariantViolation(
                "EXECUTION_RAW_EVIDENCE_MISSING_OR_CORRUPT"
            )
        if not self.raw_evidence_store.receipts(content_sha256):
            raise InvariantViolation("EXECUTION_RAW_EVIDENCE_RECEIPT_MISSING")

    @staticmethod
    def _price(data: Mapping[str, Any]) -> Price:
        return Price.parse(
            str(data["currency"]),
            data["value"],
            tick_size=data["tick_size"],
        )

    @staticmethod
    def _quantity(data: Mapping[str, Any], *, positive: bool = False) -> Quantity:
        return (
            Quantity.positive(data["value"])
            if positive
            else Quantity.parse(data["value"])
        )

    @staticmethod
    def _money(data: Mapping[str, Any]) -> Money:
        return Money(str(data["currency"]), int(data["minor_units"]))

    def _from_row(self, row: sqlite3.Row) -> ExecutionOutcome:
        try:
            decoded = _decode_canonical(json.loads(str(row["record_json"])))
            data = _mapping(decoded, "INVALID_EXECUTION_RECORD")
            context_data = _mapping(
                data["context"],
                "INVALID_EXECUTION_CONTEXT_RECORD",
            )
            context = ExecutionContext(
                instrument_id=str(context_data["instrument_id"]),
                venue_id=context_data["venue_id"],
                order_type=OrderType(str(context_data["order_type"])),
                side=OrderSide(str(context_data["side"])),
                marketability=Marketability(
                    str(context_data["marketability"])
                ),
                size_bucket=str(context_data["size_bucket"]),
                regime=str(context_data["regime"]),
            )
            average_fill = data["average_fill_price"]
            outcome = ExecutionOutcome(
                outcome_id=str(data["outcome_id"]),
                version=int(data["version"]),
                order_id=str(data["order_id"]),
                context=context,
                origin=EvidenceOrigin(str(data["origin"])),
                source_id=str(data["source_id"]),
                external_execution_id=(
                    None
                    if data["external_execution_id"] is None
                    else str(data["external_execution_id"])
                ),
                raw_content_sha256=str(data["raw_content_sha256"]),
                submitted_quantity=self._quantity(
                    _mapping(
                        data["submitted_quantity"],
                        "INVALID_SUBMITTED_QUANTITY_RECORD",
                    ),
                    positive=True,
                ),
                filled_quantity=self._quantity(
                    _mapping(
                        data["filled_quantity"],
                        "INVALID_FILLED_QUANTITY_RECORD",
                    )
                ),
                arrival_price=self._price(
                    _mapping(
                        data["arrival_price"],
                        "INVALID_ARRIVAL_PRICE_RECORD",
                    )
                ),
                average_fill_price=(
                    None
                    if average_fill is None
                    else self._price(
                        _mapping(
                            average_fill,
                            "INVALID_FILL_PRICE_RECORD",
                        )
                    )
                ),
                fee=self._money(
                    _mapping(data["fee"], "INVALID_FEE_RECORD")
                ),
                financing=self._money(
                    _mapping(
                        data["financing"],
                        "INVALID_FINANCING_RECORD",
                    )
                ),
                opportunity_cost=self._money(
                    _mapping(
                        data["opportunity_cost"],
                        "INVALID_OPPORTUNITY_COST_RECORD",
                    )
                ),
                submitted_at_ns=int(data["submitted_at_ns"]),
                acknowledged_at_ns=int(data["acknowledged_at_ns"]),
                completed_at_ns=int(data["completed_at_ns"]),
                cancelled=bool(data["cancelled"]),
                rejected=bool(data["rejected"]),
                live_trading_state=str(data["live_trading_state"]),
                profitability_state=str(data["profitability_state"]),
            )
        except Exception as exc:
            raise InvariantViolation(
                f"EXECUTION_OUTCOME_HASH_MISMATCH:"
                f"{row['outcome_id']}:{row['version']}"
            ) from exc
        if (
            outcome.sha256() != str(row["record_sha256"])
            or canonical_json(outcome.canonical_dict())
            != str(row["record_json"])
            or outcome.context.sha256() != str(row["context_sha256"])
            or canonical_sha256(outcome.identity_tuple())
            != str(row["identity_sha256"])
        ):
            raise InvariantViolation(
                f"EXECUTION_OUTCOME_HASH_MISMATCH:"
                f"{outcome.outcome_id}:{outcome.version}"
            )
        self._verify_raw(outcome.raw_content_sha256)
        return outcome

    def append(self, outcome: ExecutionOutcome) -> bool:
        self._verify_raw(outcome.raw_content_sha256)
        record_json = canonical_json(outcome.canonical_dict())
        record_sha = outcome.sha256()
        identity_sha = canonical_sha256(outcome.identity_tuple())
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                """
                SELECT * FROM execution_outcomes
                WHERE outcome_id = ? AND version = ?
                """,
                (outcome.outcome_id, outcome.version),
            ).fetchone()
            if existing is not None:
                stored = self._from_row(existing)
                if stored.sha256() != record_sha:
                    raise DuplicateConflict(
                        f"EXECUTION_OUTCOME_VERSION_CONFLICT:"
                        f"{outcome.outcome_id}:{outcome.version}"
                    )
                self._connection.execute("COMMIT")
                return False
            latest = self._connection.execute(
                """
                SELECT * FROM execution_outcomes
                WHERE outcome_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (outcome.outcome_id,),
            ).fetchone()
            expected = 1 if latest is None else int(latest["version"]) + 1
            if outcome.version != expected:
                raise InvariantViolation(
                    f"EXECUTION_OUTCOME_VERSION_SEQUENCE:"
                    f"expected={expected}:actual={outcome.version}"
                )
            if latest is not None:
                previous = self._from_row(latest)
                if outcome.identity_tuple() != previous.identity_tuple():
                    raise InvariantViolation(
                        "EXECUTION_OUTCOME_IDENTITY_MUTATION"
                    )
            self._connection.execute(
                """
                INSERT INTO execution_outcomes(
                    outcome_id, version, origin, context_sha256,
                    identity_sha256, raw_content_sha256,
                    record_json, record_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.outcome_id,
                    outcome.version,
                    outcome.origin.value,
                    outcome.context.sha256(),
                    identity_sha,
                    outcome.raw_content_sha256,
                    record_json,
                    record_sha,
                ),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def history(self, outcome_id: str) -> tuple[ExecutionOutcome, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM execution_outcomes
            WHERE outcome_id = ? ORDER BY version
            """,
            (outcome_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def outcomes(
        self,
        *,
        origin: EvidenceOrigin | None = None,
    ) -> tuple[ExecutionOutcome, ...]:
        if origin is None:
            rows = self._connection.execute(
                "SELECT * FROM execution_outcomes ORDER BY ledger_sequence"
            ).fetchall()
        else:
            if not isinstance(origin, EvidenceOrigin):
                raise InvariantViolation("INVALID_EXECUTION_EVIDENCE_ORIGIN")
            rows = self._connection.execute(
                """
                SELECT * FROM execution_outcomes
                WHERE origin = ? ORDER BY ledger_sequence
                """,
                (origin.value,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def observed_outcomes(self) -> tuple[ExecutionOutcome, ...]:
        outcomes = self.outcomes(origin=EvidenceOrigin.BROKER_OBSERVED)
        if any(not outcome.is_observed_truth for outcome in outcomes):
            raise InvariantViolation("OBSERVED_TRUTH_NAMESPACE_VIOLATION")
        return outcomes
