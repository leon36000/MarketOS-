"""SQLite-backed immutable event and evidence ledgers."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .canonical import canonical_json, canonical_sha256
from .errors import DuplicateConflict, InvariantViolation
from .events import EventEnvelope, EventKind
from .time import EventTime

_ZERO_HASH = "0" * 64


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        return {key: _decode(item) for key, item in value.items()}
    return value


def _event_from_json(text: str) -> EventEnvelope:
    data = _decode(json.loads(text))
    time = data["time"]
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
        payload=data["payload"],
    )


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


class SQLiteEventStore:
    """Append-only store with deterministic per-table hash chains."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA synchronous = FULL")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_sha256 TEXT NOT NULL,
                previous_chain_sha256 TEXT NOT NULL,
                chain_sha256 TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence (
                sequence INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                previous_chain_sha256 TEXT NOT NULL,
                chain_sha256 TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteEventStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _chain_hash(sequence: int, previous: str, item_sha256: str) -> str:
        return canonical_sha256(
            {"sequence": sequence, "previous_chain_sha256": previous, "item_sha256": item_sha256}
        )

    def _append_event_tx(self, event: EventEnvelope) -> StoredEvent:
        event_json = canonical_json(event.canonical_dict())
        event_sha256 = event.sha256()
        existing = self._connection.execute(
            "SELECT * FROM events WHERE event_id = ?", (event.event_id,)
        ).fetchone()
        if existing is not None:
            if existing["event_sha256"] != event_sha256 or existing["event_json"] != event_json:
                raise DuplicateConflict(f"EVENT_ID_CONFLICT:{event.event_id}")
            return StoredEvent(
                sequence=existing["sequence"],
                event=event,
                event_sha256=existing["event_sha256"],
                previous_chain_sha256=existing["previous_chain_sha256"],
                chain_sha256=existing["chain_sha256"],
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
            INSERT INTO events(sequence, event_id, event_sha256, previous_chain_sha256, chain_sha256, event_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sequence, event.event_id, event_sha256, previous, chain, event_json),
        )
        return StoredEvent(sequence, event, event_sha256, previous, chain, True)

    def append(self, event: EventEnvelope) -> StoredEvent:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = self._append_event_tx(event)
            self._connection.execute("COMMIT")
            return result
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def append_many(self, events: Iterable[EventEnvelope]) -> tuple[StoredEvent, ...]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            results = tuple(self._append_event_tx(event) for event in events)
            self._connection.execute("COMMIT")
            return results
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def read_all(self) -> tuple[StoredEvent, ...]:
        rows = self._connection.execute("SELECT * FROM events ORDER BY sequence").fetchall()
        return tuple(
            StoredEvent(
                sequence=row["sequence"],
                event=_event_from_json(row["event_json"]),
                event_sha256=row["event_sha256"],
                previous_chain_sha256=row["previous_chain_sha256"],
                chain_sha256=row["chain_sha256"],
                inserted=False,
            )
            for row in rows
        )

    def verify_chain(self) -> ChainVerification:
        rows = self._connection.execute("SELECT * FROM events ORDER BY sequence").fetchall()
        errors: list[str] = []
        previous = _ZERO_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            if sequence != expected_sequence:
                errors.append(f"SEQUENCE_GAP:{expected_sequence}:{sequence}")
            computed_event = canonical_sha256(_decode(json.loads(row["event_json"])))
            if computed_event != row["event_sha256"]:
                errors.append(f"EVENT_HASH_MISMATCH:{sequence}")
            if row["previous_chain_sha256"] != previous:
                errors.append(f"PREVIOUS_CHAIN_MISMATCH:{sequence}")
            computed_chain = self._chain_hash(sequence, previous, row["event_sha256"])
            if computed_chain != row["chain_sha256"]:
                errors.append(f"CHAIN_HASH_MISMATCH:{sequence}")
            previous = row["chain_sha256"]
        return ChainVerification(not errors, tuple(errors), len(rows), previous)

    def append_evidence(self, kind: str, payload: Any) -> EvidenceRecord:
        if not kind.strip():
            raise InvariantViolation("MISSING_EVIDENCE_KIND")
        payload_json = canonical_json(payload)
        evidence_sha256 = canonical_sha256({"kind": kind, "payload": payload})
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT sequence, chain_sha256 FROM evidence ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if row is None else int(row["sequence"]) + 1
            previous = _ZERO_HASH if row is None else str(row["chain_sha256"])
            chain = self._chain_hash(sequence, previous, evidence_sha256)
            self._connection.execute(
                """
                INSERT INTO evidence(sequence, kind, evidence_sha256, previous_chain_sha256, chain_sha256, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sequence, kind, evidence_sha256, previous, chain, payload_json),
            )
            self._connection.execute("COMMIT")
            return EvidenceRecord(sequence, kind, payload, evidence_sha256, previous, chain)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def read_evidence(self) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute("SELECT * FROM evidence ORDER BY sequence").fetchall()
        return tuple(
            EvidenceRecord(
                sequence=row["sequence"],
                kind=row["kind"],
                payload=_decode(json.loads(row["payload_json"])),
                evidence_sha256=row["evidence_sha256"],
                previous_chain_sha256=row["previous_chain_sha256"],
                chain_sha256=row["chain_sha256"],
            )
            for row in rows
        )

    def verify_evidence_chain(self) -> ChainVerification:
        rows = self._connection.execute("SELECT * FROM evidence ORDER BY sequence").fetchall()
        errors: list[str] = []
        previous = _ZERO_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            if sequence != expected_sequence:
                errors.append(f"SEQUENCE_GAP:{expected_sequence}:{sequence}")
            payload = _decode(json.loads(row["payload_json"]))
            computed_evidence = canonical_sha256({"kind": row["kind"], "payload": payload})
            if computed_evidence != row["evidence_sha256"]:
                errors.append(f"EVIDENCE_HASH_MISMATCH:{sequence}")
            if row["previous_chain_sha256"] != previous:
                errors.append(f"PREVIOUS_CHAIN_MISMATCH:{sequence}")
            computed_chain = self._chain_hash(sequence, previous, row["evidence_sha256"])
            if computed_chain != row["chain_sha256"]:
                errors.append(f"CHAIN_HASH_MISMATCH:{sequence}")
            previous = row["chain_sha256"]
        return ChainVerification(not errors, tuple(errors), len(rows), previous)
