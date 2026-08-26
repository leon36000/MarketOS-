"""SQLite-backed immutable event and evidence ledgers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal, DecimalException
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping

from .canonical import canonical_json, canonical_sha256
from .errors import DuplicateConflict, InvariantViolation
from .events import EventEnvelope, EventKind
from .time import EventTime

_ZERO_HASH = "0" * 64
_HEX64 = re.compile(r"[0-9a-f]{64}")
_BEGIN_IMMEDIATE = "BEGIN IMMEDIATE"
_DECIMAL_TAG = "$decimal"
_CANONICAL_TAGS = frozenset({_DECIMAL_TAG, "$datetime", "$path", "$uuid"})


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {_DECIMAL_TAG}:
            return Decimal(value[_DECIMAL_TAG])
        return {key: _decode(item) for key, item in value.items()}
    return value


def _validated_mapping_values(value: Mapping[Any, Any]) -> tuple[Any, ...]:
    normalized_items = tuple((str(key), item) for key, item in value.items())
    normalized_keys = tuple(key for key, _ in normalized_items)
    if len(set(normalized_keys)) != len(normalized_keys):
        raise InvariantViolation("NON_CANONICAL_PAYLOAD_KEYS")
    if normalized_keys == (_DECIMAL_TAG,):
        raise InvariantViolation("AMBIGUOUS_DECIMAL_MARKER")
    if len(normalized_keys) == 1 and normalized_keys[0] in _CANONICAL_TAGS:
        raise InvariantViolation(f"AMBIGUOUS_CANONICAL_TAG:{normalized_keys[0]}")
    return tuple(item for _, item in normalized_items)


def _reject_ambiguous_decimal_maps(value: Any) -> None:
    if isinstance(value, Mapping):
        for item in _validated_mapping_values(value):
            _reject_ambiguous_decimal_maps(item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_ambiguous_decimal_maps(item)
        return
    if is_dataclass(value) and not isinstance(value, type):
        _reject_ambiguous_decimal_maps(asdict(value))
        return
    canonical_method = getattr(value, "canonical_dict", None)
    if callable(canonical_method):
        _reject_ambiguous_decimal_maps(canonical_method())


def _validate_persistable_payload(value: Any, *, allow_tuple: bool) -> None:
    _reject_ambiguous_decimal_maps(value)
    _validate_persistable_value(value, allow_tuple=allow_tuple)


def _validate_persistable_value(value: Any, *, allow_tuple: bool) -> None:
    if isinstance(value, Enum):
        raise InvariantViolation(
            f"NON_RECONSTRUCTIBLE_PAYLOAD_TYPE:{type(value).__name__}"
        )
    if value is None or isinstance(value, (bool, str, int, Decimal)):
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise InvariantViolation("NON_CANONICAL_PAYLOAD_KEYS")
        for item in value.values():
            _validate_persistable_value(item, allow_tuple=allow_tuple)
        return
    if isinstance(value, list) or (allow_tuple and isinstance(value, tuple)):
        for item in value:
            _validate_persistable_value(item, allow_tuple=allow_tuple)
        return
    raise InvariantViolation(
        f"NON_RECONSTRUCTIBLE_PAYLOAD_TYPE:{type(value).__name__}"
    )


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvariantViolation(code)
    return value


def _event_from_data(value: Any) -> EventEnvelope:
    data = _mapping(value, "INVALID_EVENT_JSON")
    time = _mapping(data["time"], "INVALID_EVENT_TIME")
    return EventEnvelope(
        event_id=data["event_id"],
        kind=EventKind(data["kind"]),
        time=EventTime(
            event_time_ns=time["event_time_ns"],
            available_at_ns=time["available_at_ns"],
            received_wall_ns=time["received_wall_ns"],
            received_monotonic_ns=time["received_monotonic_ns"],
        ),
        source_id=data["source_id"],
        source_priority=data["source_priority"],
        source_sequence=data["source_sequence"],
        schema_version=data["schema_version"],
        payload=_mapping(data["payload"], "INVALID_EVENT_PAYLOAD"),
    )


def _event_from_json(text: str) -> EventEnvelope:
    return _event_from_data(_decode(json.loads(text)))


@dataclass(frozen=True, slots=True)
class StoredEvent:
    sequence: int
    event: EventEnvelope
    event_sha256: str
    previous_chain_sha256: str
    chain_sha256: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    sequence: int
    kind: str
    payload: Any
    evidence_sha256: str
    previous_chain_sha256: str
    chain_sha256: str


@dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    errors: tuple[str, ...]
    record_count: int
    head_sha256: str


@dataclass(frozen=True, slots=True)
class _TableState:
    record_count: int
    head_sha256: str


class SQLiteEventStore:
    """Append-only store with deterministic per-table hash chains."""

    _TRIGGER_CONTRACTS = {
        "events_no_update": ("events", "UPDATE", "APPEND_ONLY_EVENTS"),
        "events_no_delete": ("events", "DELETE", "APPEND_ONLY_EVENTS"),
        "evidence_no_update": ("evidence", "UPDATE", "APPEND_ONLY_EVIDENCE"),
        "evidence_no_delete": ("evidence", "DELETE", "APPEND_ONLY_EVIDENCE"),
    }

    _TABLE_CONTRACTS = {
        "events": (
            "CREATE TABLE events ( "
            "sequence INTEGER PRIMARY KEY, "
            "event_id TEXT NOT NULL UNIQUE, "
            "event_sha256 TEXT NOT NULL, "
            "previous_chain_sha256 TEXT NOT NULL, "
            "chain_sha256 TEXT NOT NULL UNIQUE, "
            "event_json TEXT NOT NULL "
            ")"
        ),
        "evidence": (
            "CREATE TABLE evidence ( "
            "sequence INTEGER PRIMARY KEY, "
            "kind TEXT NOT NULL, "
            "evidence_sha256 TEXT NOT NULL, "
            "previous_chain_sha256 TEXT NOT NULL, "
            "chain_sha256 TEXT NOT NULL UNIQUE, "
            "payload_json TEXT NOT NULL "
            ")"
        ),
    }

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA synchronous = FULL")
            existing_ledger_objects = self._has_existing_ledger_objects()
            if existing_ledger_objects:
                self._connection.execute(_BEGIN_IMMEDIATE)
                try:
                    self._verify_table_contracts()
                    self._verify_trigger_contracts(require_all=False)
                    _, _, event_verification, evidence_verification = self._verify_all_rows()
                    self._require_valid(event_verification, "EVENT_CHAIN_INTEGRITY_FAILURE")
                    self._require_valid(evidence_verification, "EVIDENCE_CHAIN_INTEGRITY_FAILURE")
                    self._create_schema()
                    self._initialize_integrity_state(transaction_open=True)
                    self._connection.execute("COMMIT")
                except Exception:
                    if self._connection.in_transaction:
                        self._connection.execute("ROLLBACK")
                    raise
            else:
                if self.path != ":memory:":
                    self._connection.execute("PRAGMA journal_mode = WAL")
                self._create_schema()
                self._initialize_integrity_state()
        except Exception:
            self._connection.close()
            self._closed = True
            raise

    def _has_existing_ledger_objects(self) -> bool:
        names = tuple(self._TABLE_CONTRACTS)
        placeholders = ",".join("?" for _ in names)
        row = self._connection.execute(
            f"SELECT 1 FROM sqlite_master WHERE name IN ({placeholders}) LIMIT 1",
            names,
        ).fetchone()
        return row is not None

    def _create_schema(self) -> None:
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_sha256 TEXT NOT NULL,
                previous_chain_sha256 TEXT NOT NULL,
                chain_sha256 TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS events_no_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_EVENTS');
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS events_no_delete
            BEFORE DELETE ON events
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_EVENTS');
            END;
            """,
            """
            CREATE TABLE IF NOT EXISTS evidence (
                sequence INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                previous_chain_sha256 TEXT NOT NULL,
                chain_sha256 TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS evidence_no_update
            BEFORE UPDATE ON evidence
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_EVIDENCE');
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS evidence_no_delete
            BEFORE DELETE ON evidence
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_EVIDENCE');
            END;
            """,
        ):
            self._connection.execute(statement)

    def _ensure_open(self) -> None:
        if self._closed:
            raise InvariantViolation("SQLITE_EVENT_STORE_CLOSED")

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteEventStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _chain_hash(sequence: int, previous: str, item_sha256: str) -> str:
        return canonical_sha256(
            {
                "sequence": sequence,
                "previous_chain_sha256": previous,
                "item_sha256": item_sha256,
            }
        )

    @staticmethod
    def _sequence(row: sqlite3.Row, expected: int, errors: list[str]) -> int:
        try:
            sequence = int(row["sequence"])
        except (IndexError, KeyError, TypeError, ValueError):
            errors.append(f"SEQUENCE_INVALID:{expected}")
            return expected
        if sequence != expected:
            errors.append(f"SEQUENCE_GAP:{expected}:{sequence}")
        return sequence

    @staticmethod
    def _text(
        row: sqlite3.Row,
        field: str,
        code: str,
        sequence: int,
        errors: list[str],
    ) -> str:
        try:
            value = row[field]
        except (IndexError, KeyError):
            errors.append(f"{code}:{sequence}")
            return ""
        if not isinstance(value, str):
            errors.append(f"{code}:{sequence}")
            return str(value)
        return value

    @staticmethod
    def _validate_sha256(
        value: str,
        code: str,
        sequence: int,
        errors: list[str],
    ) -> None:
        if _HEX64.fullmatch(value) is None:
            errors.append(f"{code}:{sequence}")

    @staticmethod
    def _decode_event_item(
        event_text: str,
        sequence: int,
        errors: list[str],
    ) -> tuple[EventEnvelope | None, str | None]:
        try:
            decoded = _decode(json.loads(event_text))
            event = _event_from_data(decoded)
            _validate_persistable_payload(event.payload, allow_tuple=True)
            canonical_text = canonical_json(decoded)
            digest = event.sha256()
        except (
            AttributeError,
            DecimalException,
            InvariantViolation,
            KeyError,
            TypeError,
            ValueError,
        ):
            errors.append(f"EVENT_JSON_INVALID:{sequence}")
            return None, None
        if canonical_text != event_text:
            errors.append(f"EVENT_JSON_NON_CANONICAL:{sequence}")
        return event, digest

    @classmethod
    def _verify_chain_link(
        cls,
        *,
        sequence: int,
        previous: str,
        item_sha256: str,
        stored_previous: str,
        stored_chain: str,
        errors: list[str],
    ) -> str:
        if stored_previous != previous:
            errors.append(f"PREVIOUS_CHAIN_MISMATCH:{sequence}")
        computed_chain = cls._chain_hash(sequence, previous, item_sha256)
        if stored_chain != computed_chain:
            errors.append(f"CHAIN_HASH_MISMATCH:{sequence}")
        return computed_chain

    @classmethod
    def _verify_event_row(
        cls,
        row: sqlite3.Row,
        expected_sequence: int,
        previous: str,
    ) -> tuple[tuple[str, ...], str]:
        errors: list[str] = []
        sequence = cls._sequence(row, expected_sequence, errors)
        event_id = cls._text(row, "event_id", "EVENT_ID_INVALID", sequence, errors)
        event_text = cls._text(row, "event_json", "EVENT_JSON_INVALID", sequence, errors)
        stored_sha = cls._text(row, "event_sha256", "EVENT_SHA256_INVALID", sequence, errors)
        stored_previous = cls._text(
            row,
            "previous_chain_sha256",
            "PREVIOUS_CHAIN_INVALID",
            sequence,
            errors,
        )
        stored_chain = cls._text(row, "chain_sha256", "CHAIN_SHA256_INVALID", sequence, errors)
        cls._validate_sha256(stored_sha, "EVENT_SHA256_INVALID", sequence, errors)
        cls._validate_sha256(stored_previous, "PREVIOUS_CHAIN_INVALID", sequence, errors)
        cls._validate_sha256(stored_chain, "CHAIN_SHA256_INVALID", sequence, errors)

        event, digest = cls._decode_event_item(event_text, sequence, errors)
        computed_item_sha = stored_sha if digest is None else digest
        if event is not None and event.event_id != event_id:
            errors.append(f"EVENT_ID_MISMATCH:{sequence}")
        if digest is not None and digest != stored_sha:
            errors.append(f"EVENT_HASH_MISMATCH:{sequence}")
        computed_chain = cls._verify_chain_link(
            sequence=sequence,
            previous=previous,
            item_sha256=computed_item_sha,
            stored_previous=stored_previous,
            stored_chain=stored_chain,
            errors=errors,
        )
        return tuple(dict.fromkeys(errors)), computed_chain

    @classmethod
    def verify_event_rows(cls, rows: Iterable[sqlite3.Row]) -> ChainVerification:
        materialized = tuple(rows)
        errors: list[str] = []
        previous = _ZERO_HASH
        for expected_sequence, row in enumerate(materialized, start=1):
            row_errors, previous = cls._verify_event_row(
                row,
                expected_sequence,
                previous,
            )
            errors.extend(row_errors)
        return ChainVerification(
            ok=not errors,
            errors=tuple(errors),
            record_count=len(materialized),
            head_sha256=previous,
        )

    @staticmethod
    def _decode_evidence_item(
        kind: str,
        payload_text: str,
        sequence: int,
        errors: list[str],
    ) -> str | None:
        try:
            payload = _decode(json.loads(payload_text))
            _validate_persistable_payload(payload, allow_tuple=False)
            canonical_text = canonical_json(payload)
            digest = canonical_sha256({"kind": kind, "payload": payload})
        except (DecimalException, InvariantViolation, TypeError, ValueError):
            errors.append(f"EVIDENCE_JSON_INVALID:{sequence}")
            return None
        if canonical_text != payload_text:
            errors.append(f"EVIDENCE_JSON_NON_CANONICAL:{sequence}")
        return digest

    @classmethod
    def _verify_evidence_row(
        cls,
        row: sqlite3.Row,
        expected_sequence: int,
        previous: str,
    ) -> tuple[tuple[str, ...], str]:
        errors: list[str] = []
        sequence = cls._sequence(row, expected_sequence, errors)
        kind = cls._text(row, "kind", "EVIDENCE_KIND_INVALID", sequence, errors)
        payload_text = cls._text(
            row,
            "payload_json",
            "EVIDENCE_JSON_INVALID",
            sequence,
            errors,
        )
        stored_sha = cls._text(
            row,
            "evidence_sha256",
            "EVIDENCE_SHA256_INVALID",
            sequence,
            errors,
        )
        stored_previous = cls._text(
            row,
            "previous_chain_sha256",
            "PREVIOUS_CHAIN_INVALID",
            sequence,
            errors,
        )
        stored_chain = cls._text(row, "chain_sha256", "CHAIN_SHA256_INVALID", sequence, errors)
        if not kind.strip():
            errors.append(f"EVIDENCE_KIND_INVALID:{sequence}")
        cls._validate_sha256(stored_sha, "EVIDENCE_SHA256_INVALID", sequence, errors)
        cls._validate_sha256(stored_previous, "PREVIOUS_CHAIN_INVALID", sequence, errors)
        cls._validate_sha256(stored_chain, "CHAIN_SHA256_INVALID", sequence, errors)

        digest = cls._decode_evidence_item(kind, payload_text, sequence, errors)
        computed_item_sha = stored_sha if digest is None else digest
        if digest is not None and digest != stored_sha:
            errors.append(f"EVIDENCE_HASH_MISMATCH:{sequence}")
        computed_chain = cls._verify_chain_link(
            sequence=sequence,
            previous=previous,
            item_sha256=computed_item_sha,
            stored_previous=stored_previous,
            stored_chain=stored_chain,
            errors=errors,
        )
        return tuple(dict.fromkeys(errors)), computed_chain

    @classmethod
    def verify_evidence_rows(cls, rows: Iterable[sqlite3.Row]) -> ChainVerification:
        materialized = tuple(rows)
        errors: list[str] = []
        previous = _ZERO_HASH
        for expected_sequence, row in enumerate(materialized, start=1):
            row_errors, previous = cls._verify_evidence_row(
                row,
                expected_sequence,
                previous,
            )
            errors.extend(row_errors)
        return ChainVerification(
            ok=not errors,
            errors=tuple(errors),
            record_count=len(materialized),
            head_sha256=previous,
        )

    @staticmethod
    def _state(verification: ChainVerification) -> _TableState:
        return _TableState(
            record_count=verification.record_count,
            head_sha256=verification.head_sha256,
        )

    @staticmethod
    def _require_valid(verification: ChainVerification, code: str) -> None:
        if verification.ok:
            return
        details = "|".join(verification.errors)
        raise InvariantViolation(f"{code}:{details}")

    def _rows(self, table: str) -> tuple[sqlite3.Row, ...]:
        if table == "events":
            query = "SELECT * FROM events ORDER BY sequence"
        elif table == "evidence":
            query = "SELECT * FROM evidence ORDER BY sequence"
        else:
            raise InvariantViolation("INVALID_EVENT_STORE_TABLE")
        return tuple(self._connection.execute(query).fetchall())

    def _tail_state(self, table: str) -> _TableState:
        if table not in {"events", "evidence"}:
            raise InvariantViolation("INVALID_EVENT_STORE_TABLE")
        row = self._connection.execute(
            f"SELECT sequence, chain_sha256 FROM {table} ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return _TableState(0, _ZERO_HASH)
        try:
            return _TableState(int(row["sequence"]), str(row["chain_sha256"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvariantViolation("EVENT_STORE_TAIL_INTEGRITY_FAILURE") from exc

    def _data_version_value(self) -> int:
        row = self._connection.execute("PRAGMA data_version").fetchone()
        if row is None:
            raise InvariantViolation("EVENT_STORE_DATA_VERSION_UNAVAILABLE")
        return int(row[0])

    @staticmethod
    def _normalize_sql(value: Any) -> str:
        return " ".join(str(value).upper().split())

    def _verify_table_contracts(self) -> None:
        names = tuple(self._TABLE_CONTRACTS)
        placeholders = ",".join("?" for _ in names)
        rows = self._connection.execute(
            f"SELECT name, sql FROM sqlite_master "
            f"WHERE type = 'table' AND name IN ({placeholders})",
            names,
        ).fetchall()
        by_name = {str(row["name"]): row for row in rows}
        for name, expected_sql in self._TABLE_CONTRACTS.items():
            row = by_name.get(name)
            if row is None or self._normalize_sql(row["sql"]) != self._normalize_sql(expected_sql):
                raise InvariantViolation(
                    f"EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:{name}"
                )

    def _protected_trigger_rows(self, catalog: str) -> tuple[sqlite3.Row, ...]:
        if catalog not in {"sqlite_master", "sqlite_temp_master"}:
            raise InvariantViolation("INVALID_SQLITE_SCHEMA_CATALOG")
        tables = tuple(self._TABLE_CONTRACTS)
        placeholders = ",".join("?" for _ in tables)
        return tuple(
            self._connection.execute(
                f"SELECT name, tbl_name, sql FROM {catalog} "
                f"WHERE type = 'trigger' AND tbl_name IN ({placeholders})",
                tables,
            ).fetchall()
        )

    def _verify_trigger_contracts(self, *, require_all: bool = True) -> None:
        temporary_rows = self._protected_trigger_rows("sqlite_temp_master")
        if temporary_rows:
            unexpected = min(str(row["name"]) for row in temporary_rows)
            raise InvariantViolation(
                f"EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:{unexpected}"
            )
        rows = self._protected_trigger_rows("sqlite_master")
        by_name = {str(row["name"]): row for row in rows}
        unexpected_names = sorted(set(by_name) - set(self._TRIGGER_CONTRACTS))
        if unexpected_names:
            raise InvariantViolation(
                f"EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:{unexpected_names[0]}"
            )
        for name, (table, operation, message) in self._TRIGGER_CONTRACTS.items():
            row = by_name.get(name)
            if row is None:
                if require_all:
                    raise InvariantViolation(
                        f"EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:{name}"
                    )
                continue
            if str(row["tbl_name"]) != table:
                raise InvariantViolation(
                    f"EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:{name}"
                )
            normalized = self._normalize_sql(row["sql"])
            expected = self._normalize_sql(
                f"CREATE TRIGGER {name} "
                f"BEFORE {operation} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
            )
            if normalized != expected:
                raise InvariantViolation(
                    f"EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:{name}"
                )

    def _verify_schema_contracts(self) -> None:
        self._verify_table_contracts()
        self._verify_trigger_contracts()

    def _verify_all_rows(
        self,
    ) -> tuple[
        tuple[sqlite3.Row, ...],
        tuple[sqlite3.Row, ...],
        ChainVerification,
        ChainVerification,
    ]:
        event_rows = self._rows("events")
        evidence_rows = self._rows("evidence")
        event_verification = self.verify_event_rows(event_rows)
        evidence_verification = self.verify_evidence_rows(evidence_rows)
        return event_rows, evidence_rows, event_verification, evidence_verification

    def _initialize_integrity_state(self, *, transaction_open: bool = False) -> None:
        if not transaction_open:
            self._connection.execute(_BEGIN_IMMEDIATE)
        try:
            _, _, event_verification, evidence_verification = self._verify_all_rows()
            self._require_valid(event_verification, "EVENT_CHAIN_INTEGRITY_FAILURE")
            self._require_valid(evidence_verification, "EVIDENCE_CHAIN_INTEGRITY_FAILURE")
            self._verify_schema_contracts()
            data_version = self._data_version_value()
            total_changes = self._connection.total_changes
            if not transaction_open:
                self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        self._event_state = self._state(event_verification)
        self._evidence_state = self._state(evidence_verification)
        self._data_version = data_version
        self._total_changes = total_changes

    def _read_verified_snapshot(
        self,
    ) -> tuple[tuple[sqlite3.Row, ...], tuple[sqlite3.Row, ...]]:
        self._ensure_open()
        self._connection.execute("BEGIN")
        try:
            event_rows, evidence_rows, event_verification, evidence_verification = (
                self._verify_all_rows()
            )
            self._require_valid(event_verification, "EVENT_CHAIN_INTEGRITY_FAILURE")
            self._require_valid(evidence_verification, "EVIDENCE_CHAIN_INTEGRITY_FAILURE")
            self._verify_schema_contracts()
            self._connection.execute("COMMIT")
            return event_rows, evidence_rows
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _write_integrity_states(self) -> tuple[_TableState, _TableState, int]:
        observed_data_version = self._data_version_value()
        external_or_local_change = (
            observed_data_version != self._data_version
            or self._connection.total_changes != self._total_changes
        )
        event_tail = self._tail_state("events")
        evidence_tail = self._tail_state("evidence")
        tail_changed = (
            event_tail != self._event_state
            or evidence_tail != self._evidence_state
        )
        if external_or_local_change or tail_changed:
            _, _, event_verification, evidence_verification = self._verify_all_rows()
            self._require_valid(event_verification, "EVENT_CHAIN_INTEGRITY_FAILURE")
            self._require_valid(evidence_verification, "EVIDENCE_CHAIN_INTEGRITY_FAILURE")
            event_state = self._state(event_verification)
            evidence_state = self._state(evidence_verification)
        else:
            event_state = self._event_state
            evidence_state = self._evidence_state
        self._verify_schema_contracts()
        return event_state, evidence_state, observed_data_version

    def _cache_committed_states(
        self,
        event_state: _TableState,
        evidence_state: _TableState,
        data_version: int,
    ) -> None:
        self._event_state = event_state
        self._evidence_state = evidence_state
        self._data_version = data_version
        self._total_changes = self._connection.total_changes

    def _append_event_tx(self, event: EventEnvelope) -> StoredEvent:
        _validate_persistable_payload(event.payload, allow_tuple=True)
        event_json = canonical_json(event.canonical_dict())
        event_sha256 = event.sha256()
        existing = self._connection.execute(
            "SELECT * FROM events WHERE event_id = ?", (event.event_id,)
        ).fetchone()
        if existing is not None:
            if existing["event_sha256"] != event_sha256 or existing["event_json"] != event_json:
                raise DuplicateConflict(f"EVENT_ID_CONFLICT:{event.event_id}")
            return StoredEvent(
                sequence=int(existing["sequence"]),
                event=event,
                event_sha256=str(existing["event_sha256"]),
                previous_chain_sha256=str(existing["previous_chain_sha256"]),
                chain_sha256=str(existing["chain_sha256"]),
                inserted=False,
            )
        row = self._connection.execute(
            "SELECT sequence, chain_sha256 FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if row is None else int(row["sequence"]) + 1
        previous = _ZERO_HASH if row is None else str(row["chain_sha256"])
        chain = self._chain_hash(sequence, previous, event_sha256)
        self._connection.execute(
            """
            INSERT INTO events(
                sequence, event_id, event_sha256, previous_chain_sha256,
                chain_sha256, event_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sequence, event.event_id, event_sha256, previous, chain, event_json),
        )
        return StoredEvent(sequence, event, event_sha256, previous, chain, True)

    def append(self, event: EventEnvelope) -> StoredEvent:
        self._ensure_open()
        self._connection.execute(_BEGIN_IMMEDIATE)
        try:
            event_state, evidence_state, data_version = self._write_integrity_states()
            result = self._append_event_tx(event)
            if result.inserted:
                event_state = _TableState(result.sequence, result.chain_sha256)
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        self._cache_committed_states(event_state, evidence_state, data_version)
        return result

    def append_many(self, events: Iterable[EventEnvelope]) -> tuple[StoredEvent, ...]:
        self._ensure_open()
        self._connection.execute(_BEGIN_IMMEDIATE)
        try:
            event_state, evidence_state, data_version = self._write_integrity_states()
            results = tuple(self._append_event_tx(event) for event in events)
            for result in results:
                if result.inserted:
                    event_state = _TableState(result.sequence, result.chain_sha256)
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        self._cache_committed_states(event_state, evidence_state, data_version)
        return results

    def count(self) -> int:
        event_rows, _ = self._read_verified_snapshot()
        return len(event_rows)

    def read_all(self) -> tuple[StoredEvent, ...]:
        event_rows, _ = self._read_verified_snapshot()
        return tuple(
            StoredEvent(
                sequence=int(row["sequence"]),
                event=_event_from_json(str(row["event_json"])),
                event_sha256=str(row["event_sha256"]),
                previous_chain_sha256=str(row["previous_chain_sha256"]),
                chain_sha256=str(row["chain_sha256"]),
                inserted=False,
            )
            for row in event_rows
        )

    def verify_chain(self) -> ChainVerification:
        self._ensure_open()
        self._connection.execute("BEGIN")
        try:
            report = self.verify_event_rows(self._rows("events"))
            self._connection.execute("COMMIT")
            return report
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def append_evidence(self, kind: str, payload: Any) -> EvidenceRecord:
        if not isinstance(kind, str) or not kind.strip():
            raise InvariantViolation("MISSING_EVIDENCE_KIND")
        _validate_persistable_payload(payload, allow_tuple=False)
        payload_json = canonical_json(payload)
        evidence_sha256 = canonical_sha256({"kind": kind, "payload": payload})
        self._ensure_open()
        self._connection.execute(_BEGIN_IMMEDIATE)
        try:
            event_state, evidence_state, data_version = self._write_integrity_states()
            row = self._connection.execute(
                "SELECT sequence, chain_sha256 FROM evidence ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if row is None else int(row["sequence"]) + 1
            previous = _ZERO_HASH if row is None else str(row["chain_sha256"])
            chain = self._chain_hash(sequence, previous, evidence_sha256)
            self._connection.execute(
                """
                INSERT INTO evidence(
                    sequence, kind, evidence_sha256, previous_chain_sha256,
                    chain_sha256, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sequence, kind, evidence_sha256, previous, chain, payload_json),
            )
            evidence_state = _TableState(sequence, chain)
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        self._cache_committed_states(event_state, evidence_state, data_version)
        return EvidenceRecord(sequence, kind, payload, evidence_sha256, previous, chain)

    def read_evidence(self) -> tuple[EvidenceRecord, ...]:
        _, evidence_rows = self._read_verified_snapshot()
        return tuple(
            EvidenceRecord(
                sequence=int(row["sequence"]),
                kind=str(row["kind"]),
                payload=_decode(json.loads(str(row["payload_json"]))),
                evidence_sha256=str(row["evidence_sha256"]),
                previous_chain_sha256=str(row["previous_chain_sha256"]),
                chain_sha256=str(row["chain_sha256"]),
            )
            for row in evidence_rows
        )

    def verify_evidence_chain(self) -> ChainVerification:
        self._ensure_open()
        self._connection.execute("BEGIN")
        try:
            report = self.verify_evidence_rows(self._rows("evidence"))
            self._connection.execute("COMMIT")
            return report
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
