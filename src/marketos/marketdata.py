"""Canonical market-data contracts, quality gates and append-only local store.

The implementation is a provider-neutral conformance backend.  It preserves
source, channel, sequence, economic time, receipt time, knowledge time, raw
content evidence and every correction.  No production feed is selected.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from .canonical import canonical_json, canonical_sha256
from .datafabric import RawEvidenceStore
from .errors import DomainError, DuplicateConflict, InvariantViolation
from .money import Price, Quantity
from .rights import RightsPolicy
from .time import EventTime

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class IngestionDenied(DomainError):
    """Raised when legal or authority gates prohibit market-data ingestion."""


class ObservationKind(str, Enum):
    QUOTE = "QUOTE"
    TRADE = "TRADE"


class ObservationStatus(str, Enum):
    ORIGINAL = "ORIGINAL"
    CORRECTED = "CORRECTED"
    CANCELLED = "CANCELLED"


class QualityState(str, Enum):
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"


class IngestionDisposition(str, Enum):
    INSERTED_ACCEPTED = "INSERTED_ACCEPTED"
    INSERTED_QUARANTINED = "INSERTED_QUARANTINED"
    DUPLICATE = "DUPLICATE"


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _decode_canonical(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_canonical(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        if set(value) == {"$uuid"}:
            return UUID(value["$uuid"])
        return {key: _decode_canonical(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class QuotePayload:
    bid: Price
    ask: Price
    bid_size: Quantity
    ask_size: Quantity

    def __post_init__(self) -> None:
        if self.bid.currency != self.ask.currency:
            raise InvariantViolation("QUOTE_CURRENCY_MISMATCH")
        if self.bid.tick_size != self.ask.tick_size:
            raise InvariantViolation("QUOTE_TICK_SIZE_MISMATCH")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
        }


@dataclass(frozen=True, slots=True)
class TradePayload:
    price: Price
    size: Quantity
    condition_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.size.value <= 0:
            raise InvariantViolation("POSITIVE_TRADE_SIZE_REQUIRED")
        codes = tuple(self.condition_codes)
        if any(not isinstance(code, str) or not code.strip() for code in codes):
            raise InvariantViolation("INVALID_TRADE_CONDITION_CODE")
        if len(codes) != len(set(codes)):
            raise InvariantViolation("DUPLICATE_TRADE_CONDITION_CODE")
        object.__setattr__(self, "condition_codes", codes)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "price": self.price,
            "size": self.size,
            "condition_codes": self.condition_codes,
        }


MarketPayload = QuotePayload | TradePayload


@dataclass(frozen=True, slots=True)
class MarketObservation:
    observation_id: str
    version: int
    kind: ObservationKind
    status: ObservationStatus
    listing_id: UUID
    venue_id: UUID
    source_id: str
    channel_id: str
    source_sequence: int
    time: EventTime
    raw_content_sha256: str
    schema_version: str
    payload: MarketPayload

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _text(self.observation_id, "MISSING_OBSERVATION_ID"))
        object.__setattr__(self, "source_id", _text(self.source_id, "MISSING_MARKET_SOURCE_ID"))
        object.__setattr__(self, "channel_id", _text(self.channel_id, "MISSING_MARKET_CHANNEL_ID"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "MISSING_MARKET_SCHEMA_VERSION"))
        if not isinstance(self.listing_id, UUID) or not isinstance(self.venue_id, UUID):
            raise InvariantViolation("INVALID_MARKET_IDENTITY")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_OBSERVATION_VERSION")
        if self.version == 1 and self.status is not ObservationStatus.ORIGINAL:
            raise InvariantViolation("FIRST_OBSERVATION_VERSION_MUST_BE_ORIGINAL")
        if self.version > 1 and self.status is ObservationStatus.ORIGINAL:
            raise InvariantViolation("OBSERVATION_REVISION_STATUS_REQUIRED")
        if not isinstance(self.kind, ObservationKind) or not isinstance(self.status, ObservationStatus):
            raise InvariantViolation("INVALID_OBSERVATION_ENUM")
        _nonnegative_int(self.source_sequence, "INVALID_MARKET_SOURCE_SEQUENCE")
        if not _HEX64.fullmatch(self.raw_content_sha256):
            raise InvariantViolation("INVALID_RAW_CONTENT_SHA256")
        if self.kind is ObservationKind.QUOTE and not isinstance(self.payload, QuotePayload):
            raise InvariantViolation("QUOTE_PAYLOAD_REQUIRED")
        if self.kind is ObservationKind.TRADE and not isinstance(self.payload, TradePayload):
            raise InvariantViolation("TRADE_PAYLOAD_REQUIRED")
        canonical_sha256(self.payload)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "version": self.version,
            "kind": self.kind,
            "status": self.status,
            "listing_id": self.listing_id,
            "venue_id": self.venue_id,
            "source_id": self.source_id,
            "channel_id": self.channel_id,
            "source_sequence": self.source_sequence,
            "time": self.time,
            "raw_content_sha256": self.raw_content_sha256,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    max_future_skew_ns: int
    max_latency_ns: int
    crossed_quote_action: str = "QUARANTINE"
    zero_trade_price_action: str = "QUARANTINE"

    def __post_init__(self) -> None:
        _nonnegative_int(self.max_future_skew_ns, "INVALID_MAX_FUTURE_SKEW")
        _nonnegative_int(self.max_latency_ns, "INVALID_MAX_SOURCE_LATENCY")
        if self.crossed_quote_action != "QUARANTINE":
            raise InvariantViolation("CROSSED_QUOTE_MUST_QUARANTINE")
        if self.zero_trade_price_action != "QUARANTINE":
            raise InvariantViolation("ZERO_TRADE_PRICE_MUST_QUARANTINE")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "max_future_skew_ns": self.max_future_skew_ns,
            "max_latency_ns": self.max_latency_ns,
            "crossed_quote_action": self.crossed_quote_action,
            "zero_trade_price_action": self.zero_trade_price_action,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class IngestionResult:
    disposition: IngestionDisposition
    observation_id: str
    version: int
    quality_state: QualityState
    reasons: tuple[str, ...]
    observation_sha256: str
    quality_policy_sha256: str
    rights_policy_sha256: str
    quality_decision_sha256: str
    inserted: bool
    live_trading_state: str = "HARD_LOCKED"

    def canonical_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "observation_id": self.observation_id,
            "version": self.version,
            "quality_state": self.quality_state,
            "reasons": self.reasons,
            "observation_sha256": self.observation_sha256,
            "quality_policy_sha256": self.quality_policy_sha256,
            "rights_policy_sha256": self.rights_policy_sha256,
            "quality_decision_sha256": self.quality_decision_sha256,
            "inserted": self.inserted,
            "live_trading_state": self.live_trading_state,
        }


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    observation: MarketObservation
    reasons: tuple[str, ...]
    quality_decision_sha256: str


class MarketDataStore:
    """SQLite append-only canonical store with fail-closed quality admission."""

    live_trading_state = "HARD_LOCKED"
    provider_selected = False
    production_feed_qualified = False

    def __init__(self, path: str | Path, *, raw_evidence_store: RawEvidenceStore) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_evidence_store = raw_evidence_store
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_observations (
                observation_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                venue_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                source_sequence INTEGER NOT NULL,
                event_time_ns INTEGER NOT NULL,
                available_at_ns INTEGER NOT NULL,
                received_wall_ns INTEGER NOT NULL,
                received_monotonic_ns INTEGER NOT NULL,
                raw_content_sha256 TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                observation_sha256 TEXT NOT NULL,
                quality_policy_sha256 TEXT NOT NULL,
                rights_policy_sha256 TEXT NOT NULL,
                quality_state TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                quality_decision_sha256 TEXT NOT NULL,
                PRIMARY KEY(observation_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_market_observation_stream
                ON market_observations(listing_id, event_time_ns, available_at_ns);
            CREATE TABLE IF NOT EXISTS market_source_sequences (
                source_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                source_sequence INTEGER NOT NULL,
                observation_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                observation_sha256 TEXT NOT NULL,
                PRIMARY KEY(source_id, channel_id, source_sequence)
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MarketDataStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _require_rights(policy: RightsPolicy) -> None:
        for capability in ("storage", "non_display", "historical_replay"):
            if not policy.allows(capability):
                raise IngestionDenied(
                    f"MARKET_DATA_RIGHT_DENIED:{policy.policy_id}:{capability}"
                )

    @staticmethod
    def _quality_reasons(
        observation: MarketObservation,
        policy: QualityPolicy,
    ) -> list[str]:
        reasons: list[str] = []
        if observation.time.event_time_ns > observation.time.received_wall_ns + policy.max_future_skew_ns:
            reasons.append("EVENT_TIME_FUTURE_SKEW")
        elif observation.time.received_wall_ns - observation.time.event_time_ns > policy.max_latency_ns:
            reasons.append("EXCESSIVE_SOURCE_LATENCY")
        if observation.kind is ObservationKind.QUOTE:
            payload = observation.payload
            assert isinstance(payload, QuotePayload)
            if payload.bid.value > payload.ask.value:
                reasons.append("CROSSED_QUOTE")
            if payload.bid_size.value == 0 and payload.ask_size.value == 0:
                reasons.append("EMPTY_QUOTE")
        else:
            payload = observation.payload
            assert isinstance(payload, TradePayload)
            if payload.price.value == 0:
                reasons.append("ZERO_TRADE_PRICE")
        return reasons

    @staticmethod
    def _payload_from_json(kind: ObservationKind, text: str) -> MarketPayload:
        try:
            data = _decode_canonical(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise InvariantViolation("INVALID_MARKET_PAYLOAD_JSON") from exc
        if not isinstance(data, Mapping):
            raise InvariantViolation("INVALID_MARKET_PAYLOAD_JSON")

        def price(value: Any) -> Price:
            if not isinstance(value, Mapping):
                raise InvariantViolation("INVALID_MARKET_PRICE_PAYLOAD")
            return Price.parse(
                str(value["currency"]),
                value["value"],
                tick_size=value["tick_size"],
            )

        def quantity(value: Any, *, positive: bool = False) -> Quantity:
            if not isinstance(value, Mapping):
                raise InvariantViolation("INVALID_MARKET_QUANTITY_PAYLOAD")
            return (
                Quantity.positive(value["value"])
                if positive
                else Quantity.parse(value["value"])
            )

        if kind is ObservationKind.QUOTE:
            return QuotePayload(
                bid=price(data["bid"]),
                ask=price(data["ask"]),
                bid_size=quantity(data["bid_size"]),
                ask_size=quantity(data["ask_size"]),
            )
        codes = data.get("condition_codes", [])
        if not isinstance(codes, list):
            raise InvariantViolation("INVALID_TRADE_CONDITION_CODES")
        return TradePayload(
            price=price(data["price"]),
            size=quantity(data["size"], positive=True),
            condition_codes=tuple(str(code) for code in codes),
        )

    def _observation_from_row(self, row: sqlite3.Row) -> MarketObservation:
        kind = ObservationKind(str(row["kind"]))
        try:
            payload = self._payload_from_json(kind, str(row["payload_json"]))
        except (InvariantViolation, KeyError, TypeError, ValueError) as exc:
            raise InvariantViolation(
                f"MARKET_OBSERVATION_HASH_MISMATCH:{row['observation_id']}:{row['version']}"
            ) from exc
        observation = MarketObservation(
            observation_id=str(row["observation_id"]),
            version=int(row["version"]),
            kind=kind,
            status=ObservationStatus(str(row["status"])),
            listing_id=UUID(str(row["listing_id"])),
            venue_id=UUID(str(row["venue_id"])),
            source_id=str(row["source_id"]),
            channel_id=str(row["channel_id"]),
            source_sequence=int(row["source_sequence"]),
            time=EventTime(
                event_time_ns=int(row["event_time_ns"]),
                available_at_ns=int(row["available_at_ns"]),
                received_wall_ns=int(row["received_wall_ns"]),
                received_monotonic_ns=int(row["received_monotonic_ns"]),
            ),
            raw_content_sha256=str(row["raw_content_sha256"]),
            schema_version=str(row["schema_version"]),
            payload=payload,
        )
        if observation.sha256() != str(row["observation_sha256"]):
            raise InvariantViolation(
                f"MARKET_OBSERVATION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        if not self.raw_evidence_store.verify(observation.raw_content_sha256):
            raise InvariantViolation(
                f"MARKET_RAW_EVIDENCE_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        try:
            quality_state = QualityState(str(row["quality_state"]))
            reasons_value = json.loads(row["reasons_json"])
            if not isinstance(reasons_value, list) or any(
                not isinstance(reason, str) for reason in reasons_value
            ):
                raise ValueError("invalid reasons")
            reasons = tuple(reasons_value)
            quality_policy_sha256 = str(row["quality_policy_sha256"])
            rights_policy_sha256 = str(row["rights_policy_sha256"])
            if not _HEX64.fullmatch(quality_policy_sha256) or not _HEX64.fullmatch(
                rights_policy_sha256
            ):
                raise ValueError("invalid policy hash")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise InvariantViolation(
                f"MARKET_QUALITY_DECISION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            ) from exc
        decision_payload = {
            "observation_sha256": observation.sha256(),
            "quality_policy_sha256": quality_policy_sha256,
            "rights_policy_sha256": rights_policy_sha256,
            "quality_state": quality_state,
            "reasons": reasons,
        }
        if canonical_sha256(decision_payload) != str(row["quality_decision_sha256"]):
            raise InvariantViolation(
                f"MARKET_QUALITY_DECISION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        return observation

    @staticmethod
    def _result_from_row(row: sqlite3.Row, *, duplicate: bool) -> IngestionResult:
        state = QualityState(str(row["quality_state"]))
        return IngestionResult(
            disposition=(
                IngestionDisposition.DUPLICATE
                if duplicate
                else (
                    IngestionDisposition.INSERTED_ACCEPTED
                    if state is QualityState.ACCEPTED
                    else IngestionDisposition.INSERTED_QUARANTINED
                )
            ),
            observation_id=str(row["observation_id"]),
            version=int(row["version"]),
            quality_state=state,
            reasons=tuple(json.loads(row["reasons_json"])),
            observation_sha256=str(row["observation_sha256"]),
            quality_policy_sha256=str(row["quality_policy_sha256"]),
            rights_policy_sha256=str(row["rights_policy_sha256"]),
            quality_decision_sha256=str(row["quality_decision_sha256"]),
            inserted=not duplicate,
        )

    def ingest(
        self,
        observation: MarketObservation,
        *,
        quality_policy: QualityPolicy,
        rights_policy: RightsPolicy,
    ) -> IngestionResult:
        self._require_rights(rights_policy)
        observation_sha = observation.sha256()
        quality_policy_sha256 = quality_policy.sha256()
        rights_policy_sha256 = rights_policy.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM market_observations WHERE observation_id = ? AND version = ?",
                (observation.observation_id, observation.version),
            ).fetchone()
            if existing is not None:
                if str(existing["observation_sha256"]) != observation_sha:
                    raise DuplicateConflict(
                        f"MARKET_OBSERVATION_VERSION_CONFLICT:{observation.observation_id}:{observation.version}"
                    )
                if (
                    str(existing["quality_policy_sha256"]) != quality_policy_sha256
                    or str(existing["rights_policy_sha256"]) != rights_policy_sha256
                ):
                    raise DuplicateConflict(
                        f"INGESTION_POLICY_CONFLICT:{observation.observation_id}:{observation.version}"
                    )
                self._observation_from_row(existing)
                result = self._result_from_row(existing, duplicate=True)
                self._connection.execute("COMMIT")
                return result

            latest = self._connection.execute(
                "SELECT * FROM market_observations WHERE observation_id = ? ORDER BY version DESC LIMIT 1",
                (observation.observation_id,),
            ).fetchone()
            expected_version = 1 if latest is None else int(latest["version"]) + 1
            if observation.version != expected_version:
                raise InvariantViolation(
                    f"MARKET_OBSERVATION_VERSION_SEQUENCE:expected={expected_version}:actual={observation.version}"
                )
            if latest is not None:
                immutable_identity = (
                    str(observation.kind.value),
                    str(observation.listing_id),
                    str(observation.venue_id),
                    observation.source_id,
                    observation.channel_id,
                    observation.time.event_time_ns,
                )
                previous_identity = (
                    str(latest["kind"]),
                    str(latest["listing_id"]),
                    str(latest["venue_id"]),
                    str(latest["source_id"]),
                    str(latest["channel_id"]),
                    int(latest["event_time_ns"]),
                )
                if immutable_identity != previous_identity:
                    raise InvariantViolation("MARKET_OBSERVATION_IDENTITY_MUTATION")
                if observation.time.available_at_ns < int(latest["available_at_ns"]):
                    raise InvariantViolation("MARKET_OBSERVATION_KNOWLEDGE_TIME_REGRESSION")

            reasons = self._quality_reasons(observation, quality_policy)
            if not self.raw_evidence_store.verify(observation.raw_content_sha256):
                reasons.append("RAW_EVIDENCE_MISSING_OR_CORRUPT")

            sequence_row = self._connection.execute(
                """
                SELECT observation_id, version, observation_sha256
                FROM market_source_sequences
                WHERE source_id = ? AND channel_id = ? AND source_sequence = ?
                """,
                (observation.source_id, observation.channel_id, observation.source_sequence),
            ).fetchone()
            sequence_insert = sequence_row is None
            if sequence_row is not None:
                reasons.append("SEQUENCE_COLLISION")
            else:
                highest_row = self._connection.execute(
                    """
                    SELECT MAX(source_sequence) AS highest
                    FROM market_source_sequences
                    WHERE source_id = ? AND channel_id = ?
                    """,
                    (observation.source_id, observation.channel_id),
                ).fetchone()
                highest = None if highest_row is None else highest_row["highest"]
                if highest is not None:
                    highest_int = int(highest)
                    if observation.source_sequence > highest_int + 1:
                        reasons.append(
                            f"SEQUENCE_GAP:expected={highest_int + 1}:actual={observation.source_sequence}"
                        )
                    elif observation.source_sequence <= highest_int:
                        reasons.append("SEQUENCE_REGRESSION")

            reasons_tuple = tuple(dict.fromkeys(reasons))
            quality_state = (
                QualityState.QUARANTINED if reasons_tuple else QualityState.ACCEPTED
            )
            decision_payload = {
                "observation_sha256": observation_sha,
                "quality_policy_sha256": quality_policy_sha256,
                "rights_policy_sha256": rights_policy_sha256,
                "quality_state": quality_state,
                "reasons": reasons_tuple,
            }
            decision_sha = canonical_sha256(decision_payload)
            self._connection.execute(
                """
                INSERT INTO market_observations(
                    observation_id, version, kind, status, listing_id, venue_id,
                    source_id, channel_id, source_sequence, event_time_ns,
                    available_at_ns, received_wall_ns, received_monotonic_ns,
                    raw_content_sha256, schema_version, payload_json,
                    observation_sha256, quality_policy_sha256,
                    rights_policy_sha256, quality_state, reasons_json,
                    quality_decision_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.version,
                    observation.kind.value,
                    observation.status.value,
                    str(observation.listing_id),
                    str(observation.venue_id),
                    observation.source_id,
                    observation.channel_id,
                    observation.source_sequence,
                    observation.time.event_time_ns,
                    observation.time.available_at_ns,
                    observation.time.received_wall_ns,
                    observation.time.received_monotonic_ns,
                    observation.raw_content_sha256,
                    observation.schema_version,
                    canonical_json(observation.payload),
                    observation_sha,
                    quality_policy_sha256,
                    rights_policy_sha256,
                    quality_state.value,
                    json.dumps(reasons_tuple, separators=(",", ":")),
                    decision_sha,
                ),
            )
            if sequence_insert:
                self._connection.execute(
                    """
                    INSERT INTO market_source_sequences(
                        source_id, channel_id, source_sequence,
                        observation_id, version, observation_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation.source_id,
                        observation.channel_id,
                        observation.source_sequence,
                        observation.observation_id,
                        observation.version,
                        observation_sha,
                    ),
                )
            row = self._connection.execute(
                "SELECT * FROM market_observations WHERE observation_id = ? AND version = ?",
                (observation.observation_id, observation.version),
            ).fetchone()
            assert row is not None
            result = self._result_from_row(row, duplicate=False)
            self._connection.execute("COMMIT")
            return result
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def _row_for_version(self, observation_id: str, version: int) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM market_observations WHERE observation_id = ? AND version = ?",
            (observation_id, version),
        ).fetchone()

    def history(self, observation_id: str) -> tuple[MarketObservation, ...]:
        rows = self._connection.execute(
            "SELECT * FROM market_observations WHERE observation_id = ? ORDER BY version",
            (observation_id,),
        ).fetchall()
        return tuple(self._observation_from_row(row) for row in rows)

    def as_known(
        self,
        observation_id: str,
        *,
        knowledge_time_ns: int,
    ) -> tuple[MarketObservation, QualityState, tuple[str, ...]] | None:
        _nonnegative_int(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        row = self._connection.execute(
            """
            SELECT * FROM market_observations
            WHERE observation_id = ? AND available_at_ns <= ?
            ORDER BY available_at_ns DESC, version DESC
            LIMIT 1
            """,
            (observation_id, knowledge_time_ns),
        ).fetchone()
        if row is None:
            return None
        return (
            self._observation_from_row(row),
            QualityState(str(row["quality_state"])),
            tuple(json.loads(row["reasons_json"])),
        )

    def effective_as_known(
        self,
        observation_id: str,
        *,
        knowledge_time_ns: int,
    ) -> MarketObservation | None:
        known = self.as_known(observation_id, knowledge_time_ns=knowledge_time_ns)
        if known is None:
            return None
        observation, state, _ = known
        if state is not QualityState.ACCEPTED:
            return None
        if observation.status is ObservationStatus.CANCELLED:
            return None
        return observation

    def stream(
        self,
        listing_id: UUID,
        start_event_time_ns: int,
        end_event_time_ns: int,
        *,
        knowledge_time_ns: int,
    ) -> tuple[MarketObservation, ...]:
        _nonnegative_int(start_event_time_ns, "INVALID_STREAM_START")
        _nonnegative_int(end_event_time_ns, "INVALID_STREAM_END")
        _nonnegative_int(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        if end_event_time_ns < start_event_time_ns:
            raise InvariantViolation("INVALID_MARKET_STREAM_INTERVAL")
        ids = [
            str(row["observation_id"])
            for row in self._connection.execute(
                "SELECT DISTINCT observation_id FROM market_observations WHERE listing_id = ?",
                (str(listing_id),),
            ).fetchall()
        ]
        observations: list[MarketObservation] = []
        for observation_id in ids:
            observation = self.effective_as_known(
                observation_id,
                knowledge_time_ns=knowledge_time_ns,
            )
            if (
                observation is not None
                and start_event_time_ns <= observation.time.event_time_ns < end_event_time_ns
            ):
                observations.append(observation)
        return tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.time.event_time_ns,
                    item.source_id,
                    item.channel_id,
                    item.source_sequence,
                    item.observation_id,
                ),
            )
        )

    def quarantine_records(self) -> tuple[QuarantineRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM market_observations
            WHERE quality_state = ?
            ORDER BY available_at_ns, observation_id, version
            """,
            (QualityState.QUARANTINED.value,),
        ).fetchall()
        return tuple(
            QuarantineRecord(
                observation=self._observation_from_row(row),
                reasons=tuple(json.loads(row["reasons_json"])),
                quality_decision_sha256=str(row["quality_decision_sha256"]),
            )
            for row in rows
        )
