"""Immutable shadow counterfactual evidence.

Shadow comparisons record what MARKET-OS would have attempted and what later
market observations made observable.  They remain counterfactual even when
linked to a separately verified broker-observed fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping

from .canonical import canonical_json, canonical_sha256
from .datafabric import RawEvidenceStore
from .errors import DuplicateConflict, InvariantViolation
from .execution_evidence import (
    EvidenceOrigin,
    ExecutionContext,
    ExecutionEvidenceLedger,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _identifier(value: str, code: str) -> str:
    normalized = _text(value, code)
    if not _SAFE_ID.fullmatch(normalized):
        raise InvariantViolation(code)
    return normalized


def _positive_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvariantViolation(code)
    return value


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _digest(value: str | None, code: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise InvariantViolation(code)
    return value


def _decimal(value: Decimal | None, code: str, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(code)
    return value


def _decode_canonical(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_canonical(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(str(value["$decimal"]))
        if set(value) == {"$uuid"}:
            from uuid import UUID

            return UUID(str(value["$uuid"]))
        return {str(key): _decode_canonical(item) for key, item in value.items()}
    return value


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvariantViolation(code)
    return value


class ShadowDecision(str, Enum):
    TRADE_INTENT = "TRADE_INTENT"
    NO_TRADE = "NO_TRADE"
    ABSTAIN = "ABSTAIN"
    CANCEL_COUNTERFACTUAL = "CANCEL_COUNTERFACTUAL"


_TRADE_DECISIONS = {
    ShadowDecision.TRADE_INTENT,
    ShadowDecision.CANCEL_COUNTERFACTUAL,
}


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    comparison_id: str
    version: int
    strategy_id: str
    strategy_version: int
    decision: ShadowDecision
    decision_reason: str
    intent_id: str | None
    intent_sha256: str | None
    context: ExecutionContext
    prediction_sha256: str | None
    model_definition_sha256: str | None
    reference_market_sha256: str
    source_dataset_sha256: str
    raw_content_sha256: str
    decision_time_ns: int
    prediction_available_at_ns: int
    later_observation_available_at_ns: int
    predicted_fill_ratio: Decimal | None
    predicted_shortfall_bps: Decimal | None
    opportunity_fill_ratio: Decimal | None
    opportunity_shortfall_bps: Decimal | None
    fill_ratio_gap: Decimal | None
    shortfall_gap_bps: Decimal | None
    linked_broker_outcome_sha256: str | None
    broker_fill_claimed: bool = False
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"
    strategy_edge_proven: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "comparison_id",
            _identifier(self.comparison_id, "INVALID_SHADOW_COMPARISON_ID"),
        )
        _positive_int(self.version, "INVALID_SHADOW_VERSION")
        object.__setattr__(
            self,
            "strategy_id",
            _identifier(self.strategy_id, "INVALID_SHADOW_STRATEGY_ID"),
        )
        _positive_int(self.strategy_version, "INVALID_SHADOW_STRATEGY_VERSION")
        if not isinstance(self.decision, ShadowDecision):
            raise InvariantViolation("INVALID_SHADOW_DECISION")
        object.__setattr__(
            self,
            "decision_reason",
            _text(self.decision_reason, "MISSING_SHADOW_DECISION_REASON"),
        )
        if not isinstance(self.context, ExecutionContext):
            raise InvariantViolation("INVALID_SHADOW_CONTEXT")
        for value, code in (
            (self.reference_market_sha256, "INVALID_REFERENCE_MARKET_SHA256"),
            (self.source_dataset_sha256, "INVALID_SOURCE_DATASET_SHA256"),
            (self.raw_content_sha256, "INVALID_SHADOW_RAW_CONTENT_SHA256"),
        ):
            _digest(value, code)
        _nonnegative_int(self.decision_time_ns, "INVALID_SHADOW_DECISION_TIME")
        _nonnegative_int(
            self.prediction_available_at_ns,
            "INVALID_SHADOW_PREDICTION_TIME",
        )
        _nonnegative_int(
            self.later_observation_available_at_ns,
            "INVALID_SHADOW_OBSERVATION_TIME",
        )
        if self.prediction_available_at_ns > self.decision_time_ns:
            raise InvariantViolation("SHADOW_PREDICTION_LOOKAHEAD")
        if self.later_observation_available_at_ns < self.decision_time_ns:
            raise InvariantViolation("SHADOW_OBSERVATION_BEFORE_DECISION")
        if self.broker_fill_claimed is not False:
            raise InvariantViolation("SHADOW_BROKER_FILL_CLAIM_FORBIDDEN")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("SHADOW_EVIDENCE_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("SHADOW_EVIDENCE_CANNOT_PROVE_PROFITABILITY")
        if self.strategy_edge_proven is not False:
            raise InvariantViolation("SHADOW_EVIDENCE_CANNOT_PROVE_EDGE")

        intent_id = self.intent_id
        intent_sha = self.intent_sha256
        prediction_sha = self.prediction_sha256
        model_sha = self.model_definition_sha256
        predicted_fill = _decimal(
            self.predicted_fill_ratio,
            "INVALID_SHADOW_PREDICTED_FILL_RATIO",
            optional=True,
        )
        predicted_shortfall = _decimal(
            self.predicted_shortfall_bps,
            "INVALID_SHADOW_PREDICTED_SHORTFALL",
            optional=True,
        )
        opportunity_fill = _decimal(
            self.opportunity_fill_ratio,
            "INVALID_SHADOW_OPPORTUNITY_FILL_RATIO",
            optional=True,
        )
        opportunity_shortfall = _decimal(
            self.opportunity_shortfall_bps,
            "INVALID_SHADOW_OPPORTUNITY_SHORTFALL",
            optional=True,
        )
        fill_gap = _decimal(
            self.fill_ratio_gap,
            "INVALID_SHADOW_FILL_RATIO_GAP",
            optional=True,
        )
        shortfall_gap = _decimal(
            self.shortfall_gap_bps,
            "INVALID_SHADOW_SHORTFALL_GAP",
            optional=True,
        )
        for ratio in (predicted_fill, opportunity_fill):
            if ratio is not None and not Decimal("0") <= ratio <= Decimal("1"):
                raise InvariantViolation("SHADOW_RATIO_OUT_OF_RANGE")

        if self.decision in _TRADE_DECISIONS:
            if intent_id is None or intent_sha is None:
                raise InvariantViolation("SHADOW_INTENT_REQUIRED")
            object.__setattr__(
                self,
                "intent_id",
                _identifier(intent_id, "INVALID_SHADOW_INTENT_ID"),
            )
            _digest(intent_sha, "INVALID_SHADOW_INTENT_SHA256")
            if prediction_sha is None or model_sha is None:
                raise InvariantViolation("SHADOW_PREDICTION_REQUIRED")
            _digest(prediction_sha, "INVALID_SHADOW_PREDICTION_SHA256")
            _digest(model_sha, "INVALID_SHADOW_MODEL_DEFINITION_SHA256")
            if predicted_fill is None or predicted_shortfall is None:
                raise InvariantViolation("SHADOW_PREDICTION_REQUIRED")
            if opportunity_fill is None or opportunity_shortfall is None:
                raise InvariantViolation("SHADOW_OPPORTUNITY_REQUIRED")
            if fill_gap is None or shortfall_gap is None:
                raise InvariantViolation("SHADOW_DISCREPANCY_REQUIRED")
            if fill_gap != opportunity_fill - predicted_fill:
                raise InvariantViolation("SHADOW_FILL_RATIO_GAP_MISMATCH")
            if shortfall_gap != opportunity_shortfall - predicted_shortfall:
                raise InvariantViolation("SHADOW_SHORTFALL_GAP_MISMATCH")
        else:
            if intent_id is not None or intent_sha is not None:
                raise InvariantViolation("NON_TRADE_SHADOW_INTENT_FORBIDDEN")
            if prediction_sha is not None or model_sha is not None:
                raise InvariantViolation("NON_TRADE_SHADOW_PREDICTION_FORBIDDEN")
            if predicted_fill is not None or predicted_shortfall is not None:
                raise InvariantViolation("NON_TRADE_SHADOW_PREDICTION_FORBIDDEN")
            if fill_gap is not None or shortfall_gap is not None:
                raise InvariantViolation("NON_TRADE_SHADOW_GAP_FORBIDDEN")
            if (opportunity_fill is None) != (opportunity_shortfall is None):
                raise InvariantViolation("INCOMPLETE_SHADOW_OPPORTUNITY")

        if self.linked_broker_outcome_sha256 is not None:
            _digest(
                self.linked_broker_outcome_sha256,
                "INVALID_SHADOW_BROKER_LINK_SHA256",
            )

    @property
    def evidence_origin(self) -> EvidenceOrigin:
        return EvidenceOrigin.SHADOW_COUNTERFACTUAL

    @property
    def is_observed_truth(self) -> bool:
        return False

    @property
    def missed_opportunity(self) -> bool:
        return (
            self.opportunity_fill_ratio is not None
            and self.opportunity_fill_ratio > 0
        )

    def identity_tuple(self) -> tuple[object, ...]:
        return (
            self.comparison_id,
            self.strategy_id,
            self.strategy_version,
            self.decision,
            self.intent_id,
            self.intent_sha256,
            self.context.sha256(),
            self.prediction_sha256,
            self.model_definition_sha256,
            self.reference_market_sha256,
            self.source_dataset_sha256,
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "version": self.version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "intent_id": self.intent_id,
            "intent_sha256": self.intent_sha256,
            "context": self.context,
            "prediction_sha256": self.prediction_sha256,
            "model_definition_sha256": self.model_definition_sha256,
            "reference_market_sha256": self.reference_market_sha256,
            "source_dataset_sha256": self.source_dataset_sha256,
            "raw_content_sha256": self.raw_content_sha256,
            "decision_time_ns": self.decision_time_ns,
            "prediction_available_at_ns": self.prediction_available_at_ns,
            "later_observation_available_at_ns": (
                self.later_observation_available_at_ns
            ),
            "predicted_fill_ratio": self.predicted_fill_ratio,
            "predicted_shortfall_bps": self.predicted_shortfall_bps,
            "opportunity_fill_ratio": self.opportunity_fill_ratio,
            "opportunity_shortfall_bps": self.opportunity_shortfall_bps,
            "fill_ratio_gap": self.fill_ratio_gap,
            "shortfall_gap_bps": self.shortfall_gap_bps,
            "linked_broker_outcome_sha256": (
                self.linked_broker_outcome_sha256
            ),
            "broker_fill_claimed": self.broker_fill_claimed,
            "evidence_origin": self.evidence_origin,
            "is_observed_truth": self.is_observed_truth,
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
            "strategy_edge_proven": self.strategy_edge_proven,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class ShadowEvidenceLedger:
    """Append-only ledger for shadow-only counterfactual comparisons."""

    live_trading_state = "HARD_LOCKED"
    profitability_state = "UNPROVEN"
    broker_selected = False
    shadow_deployment_qualified = False
    execution_simulator_calibrated = False
    strategy_edge_proven = False

    def __init__(
        self,
        path: str | Path,
        *,
        raw_evidence_store: RawEvidenceStore,
        execution_evidence_ledger: ExecutionEvidenceLedger,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_evidence_store = raw_evidence_store
        self.execution_evidence_ledger = execution_evidence_ledger
        self._closed = False
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS shadow_comparisons (
                ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                comparison_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                decision TEXT NOT NULL,
                identity_sha256 TEXT NOT NULL,
                raw_content_sha256 TEXT NOT NULL,
                linked_broker_outcome_sha256 TEXT,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                UNIQUE(comparison_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_shadow_decision
                ON shadow_comparisons(decision, ledger_sequence);
            CREATE TRIGGER IF NOT EXISTS shadow_comparisons_no_update
            BEFORE UPDATE ON shadow_comparisons
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_SHADOW_EVIDENCE');
            END;
            CREATE TRIGGER IF NOT EXISTS shadow_comparisons_no_delete
            BEFORE DELETE ON shadow_comparisons
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_SHADOW_EVIDENCE');
            END;
            """
        )

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def __enter__(self) -> "ShadowEvidenceLedger":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _verify_raw(self, content_sha256: str) -> None:
        if not self.raw_evidence_store.verify(content_sha256):
            raise InvariantViolation(
                "SHADOW_RAW_EVIDENCE_MISSING_OR_CORRUPT"
            )
        if not self.raw_evidence_store.receipts(content_sha256):
            raise InvariantViolation("SHADOW_RAW_EVIDENCE_RECEIPT_MISSING")

    def _verify_broker_link(self, linked_sha256: str | None) -> None:
        if linked_sha256 is None:
            return
        matches = tuple(
            outcome
            for outcome in self.execution_evidence_ledger.outcomes()
            if outcome.sha256() == linked_sha256
        )
        if not matches:
            raise InvariantViolation("SHADOW_BROKER_LINK_NOT_FOUND")
        if any(
            outcome.origin is not EvidenceOrigin.BROKER_OBSERVED
            for outcome in matches
        ):
            raise InvariantViolation("SHADOW_BROKER_LINK_NOT_OBSERVED")

    @staticmethod
    def _context(data: Mapping[str, Any]) -> ExecutionContext:
        from uuid import UUID
        from .orders import OrderSide, OrderType
        from .execution_evidence import Marketability

        return ExecutionContext(
            instrument_id=str(data["instrument_id"]),
            venue_id=(
                data["venue_id"]
                if isinstance(data["venue_id"], UUID)
                else UUID(str(data["venue_id"]))
            ),
            order_type=OrderType(str(data["order_type"])),
            side=OrderSide(str(data["side"])),
            marketability=Marketability(str(data["marketability"])),
            size_bucket=str(data["size_bucket"]),
            regime=str(data["regime"]),
        )

    def _from_row(self, row: sqlite3.Row) -> ShadowComparison:
        try:
            decoded = _decode_canonical(json.loads(str(row["record_json"])))
            data = _mapping(decoded, "INVALID_SHADOW_RECORD")
            comparison = ShadowComparison(
                comparison_id=str(data["comparison_id"]),
                version=int(data["version"]),
                strategy_id=str(data["strategy_id"]),
                strategy_version=int(data["strategy_version"]),
                decision=ShadowDecision(str(data["decision"])),
                decision_reason=str(data["decision_reason"]),
                intent_id=(
                    None if data["intent_id"] is None else str(data["intent_id"])
                ),
                intent_sha256=(
                    None
                    if data["intent_sha256"] is None
                    else str(data["intent_sha256"])
                ),
                context=self._context(
                    _mapping(data["context"], "INVALID_SHADOW_CONTEXT_RECORD")
                ),
                prediction_sha256=(
                    None
                    if data["prediction_sha256"] is None
                    else str(data["prediction_sha256"])
                ),
                model_definition_sha256=(
                    None
                    if data["model_definition_sha256"] is None
                    else str(data["model_definition_sha256"])
                ),
                reference_market_sha256=str(data["reference_market_sha256"]),
                source_dataset_sha256=str(data["source_dataset_sha256"]),
                raw_content_sha256=str(data["raw_content_sha256"]),
                decision_time_ns=int(data["decision_time_ns"]),
                prediction_available_at_ns=int(data["prediction_available_at_ns"]),
                later_observation_available_at_ns=int(
                    data["later_observation_available_at_ns"]
                ),
                predicted_fill_ratio=data["predicted_fill_ratio"],
                predicted_shortfall_bps=data["predicted_shortfall_bps"],
                opportunity_fill_ratio=data["opportunity_fill_ratio"],
                opportunity_shortfall_bps=data["opportunity_shortfall_bps"],
                fill_ratio_gap=data["fill_ratio_gap"],
                shortfall_gap_bps=data["shortfall_gap_bps"],
                linked_broker_outcome_sha256=(
                    None
                    if data["linked_broker_outcome_sha256"] is None
                    else str(data["linked_broker_outcome_sha256"])
                ),
                broker_fill_claimed=bool(data["broker_fill_claimed"]),
                live_trading_state=str(data["live_trading_state"]),
                profitability_state=str(data["profitability_state"]),
                strategy_edge_proven=bool(data["strategy_edge_proven"]),
            )
        except Exception as exc:
            raise InvariantViolation(
                f"SHADOW_COMPARISON_HASH_MISMATCH:"
                f"{row['comparison_id']}:{row['version']}"
            ) from exc
        if (
            comparison.sha256() != str(row["record_sha256"])
            or canonical_json(comparison.canonical_dict())
            != str(row["record_json"])
            or canonical_sha256(comparison.identity_tuple())
            != str(row["identity_sha256"])
        ):
            raise InvariantViolation(
                f"SHADOW_COMPARISON_HASH_MISMATCH:"
                f"{comparison.comparison_id}:{comparison.version}"
            )
        self._verify_raw(comparison.raw_content_sha256)
        self._verify_broker_link(comparison.linked_broker_outcome_sha256)
        return comparison

    def append(self, comparison: ShadowComparison) -> bool:
        self._verify_raw(comparison.raw_content_sha256)
        self._verify_broker_link(comparison.linked_broker_outcome_sha256)
        record_json = canonical_json(comparison.canonical_dict())
        record_sha = comparison.sha256()
        identity_sha = canonical_sha256(comparison.identity_tuple())
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                """
                SELECT * FROM shadow_comparisons
                WHERE comparison_id = ? AND version = ?
                """,
                (comparison.comparison_id, comparison.version),
            ).fetchone()
            if existing is not None:
                stored = self._from_row(existing)
                if stored.sha256() != record_sha:
                    raise DuplicateConflict(
                        f"SHADOW_COMPARISON_VERSION_CONFLICT:"
                        f"{comparison.comparison_id}:{comparison.version}"
                    )
                self._connection.execute("COMMIT")
                return False
            latest = self._connection.execute(
                """
                SELECT * FROM shadow_comparisons
                WHERE comparison_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (comparison.comparison_id,),
            ).fetchone()
            expected = 1 if latest is None else int(latest["version"]) + 1
            if comparison.version != expected:
                raise InvariantViolation(
                    f"SHADOW_VERSION_SEQUENCE:expected={expected}:"
                    f"actual={comparison.version}"
                )
            if latest is not None:
                previous = self._from_row(latest)
                if comparison.identity_tuple() != previous.identity_tuple():
                    raise InvariantViolation("SHADOW_IDENTITY_MUTATION")
            self._connection.execute(
                """
                INSERT INTO shadow_comparisons(
                    comparison_id, version, decision, identity_sha256,
                    raw_content_sha256, linked_broker_outcome_sha256,
                    record_json, record_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    comparison.comparison_id,
                    comparison.version,
                    comparison.decision.value,
                    identity_sha,
                    comparison.raw_content_sha256,
                    comparison.linked_broker_outcome_sha256,
                    record_json,
                    record_sha,
                ),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def history(self, comparison_id: str) -> tuple[ShadowComparison, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM shadow_comparisons
            WHERE comparison_id = ? ORDER BY version
            """,
            (comparison_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def comparisons(
        self,
        *,
        decision: ShadowDecision | None = None,
    ) -> tuple[ShadowComparison, ...]:
        if decision is None:
            rows = self._connection.execute(
                "SELECT * FROM shadow_comparisons ORDER BY ledger_sequence"
            ).fetchall()
        else:
            if not isinstance(decision, ShadowDecision):
                raise InvariantViolation("INVALID_SHADOW_DECISION")
            rows = self._connection.execute(
                """
                SELECT * FROM shadow_comparisons
                WHERE decision = ? ORDER BY ledger_sequence
                """,
                (decision.value,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def observed_links(self) -> tuple[tuple[str, str], ...]:
        rows = self._connection.execute(
            """
            SELECT comparison_id, linked_broker_outcome_sha256
            FROM shadow_comparisons
            WHERE linked_broker_outcome_sha256 IS NOT NULL
            ORDER BY ledger_sequence
            """
        ).fetchall()
        result: list[tuple[str, str]] = []
        for row in rows:
            comparison = self.history(str(row["comparison_id"]))[-1]
            if comparison.linked_broker_outcome_sha256 is None:
                raise InvariantViolation("SHADOW_LINK_INDEX_MISMATCH")
            result.append(
                (
                    comparison.comparison_id,
                    comparison.linked_broker_outcome_sha256,
                )
            )
        return tuple(result)
