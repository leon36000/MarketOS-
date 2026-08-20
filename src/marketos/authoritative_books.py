"""Durable paper/shadow book boundaries for the first C13 implementation slice."""
from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any, Mapping

from .canonical import canonical_json
from .errors import InvariantViolation
from .ledger import JournalEntry, Ledger, Posting, PostingSide
from .money import Money


def _decode_canonical(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_canonical(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            from decimal import Decimal

            return Decimal(str(value["$decimal"]))
        return {str(key): _decode_canonical(item) for key, item in value.items()}
    return value


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvariantViolation(code)
    return value


def _entry_from_row(row: sqlite3.Row) -> JournalEntry:
    try:
        record_json = str(row["record_json"])
        data = _mapping(_decode_canonical(json.loads(record_json)), "INVALID_JOURNAL_RECORD")
        postings = tuple(
            Posting(
                account=str(posting["account"]),
                side=PostingSide(str(posting["side"])),
                amount=Money(
                    str(_mapping(posting["amount"], "INVALID_JOURNAL_AMOUNT")["currency"]),
                    int(_mapping(posting["amount"], "INVALID_JOURNAL_AMOUNT")["minor_units"]),
                ),
            )
            for posting in data["postings"]
        )
        entry = JournalEntry(
            entry_id=str(data["entry_id"]),
            occurred_at_ns=int(data["occurred_at_ns"]),
            description=str(data["description"]),
            postings=postings,
            reversal_of=(
                None if data["reversal_of"] is None else str(data["reversal_of"])
            ),
        )
    except Exception as exc:
        raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE") from exc
    if (
        entry.sha256() != str(row["record_sha256"])
        or canonical_json(entry.canonical_dict()) != record_json
        or entry.entry_id != str(row["entry_id"])
    ):
        raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
    return entry


class DurableLedger:
    """SQLite-backed append-only wrapper around the exact in-memory ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
                ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id TEXT NOT NULL UNIQUE,
                occurred_at_ns INTEGER NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                previous_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS ledger_entries_no_update
            BEFORE UPDATE ON ledger_entries
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER');
            END;
            CREATE TRIGGER IF NOT EXISTS ledger_entries_no_delete
            BEFORE DELETE ON ledger_entries
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER');
            END;
            """
        )
        self._ledger = Ledger()
        self._load()

    def _ensure_open(self) -> None:
        if self._closed:
            raise InvariantViolation("DURABLE_LEDGER_CLOSED")

    def _load(self) -> None:
        previous_sha256 = ""
        expected_sequence = 1
        rows = self._connection.execute(
            "SELECT * FROM ledger_entries ORDER BY ledger_sequence"
        ).fetchall()
        for row in rows:
            if int(row["ledger_sequence"]) != expected_sequence:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if str(row["previous_sha256"]) != previous_sha256:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            entry = _entry_from_row(row)
            self._ledger.post(entry)
            previous_sha256 = str(row["record_sha256"])
            expected_sequence += 1

    def post(self, entry: JournalEntry) -> bool:
        self._ensure_open()
        candidate = self._ledger.clone()
        inserted = candidate.post(entry)
        if not inserted:
            return False
        record_json = canonical_json(entry.canonical_dict())
        record_sha256 = entry.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            previous = self._connection.execute(
                "SELECT record_sha256 FROM ledger_entries ORDER BY ledger_sequence DESC LIMIT 1"
            ).fetchone()
            previous_sha256 = "" if previous is None else str(previous["record_sha256"])
            self._connection.execute(
                """
                INSERT INTO ledger_entries(
                    entry_id, occurred_at_ns, record_json, record_sha256, previous_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.occurred_at_ns,
                    record_json,
                    record_sha256,
                    previous_sha256,
                ),
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        self._ledger = candidate
        return True

    def post_many(self, entries: tuple[JournalEntry, ...] | list[JournalEntry]) -> tuple[bool, ...]:
        self._ensure_open()
        pending = tuple(entries)
        candidate = self._ledger.clone()
        results: list[bool] = []
        new_entries: list[JournalEntry] = []
        for entry in pending:
            inserted = candidate.post(entry)
            results.append(inserted)
            if inserted:
                new_entries.append(entry)
        if not new_entries:
            return tuple(results)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            previous = self._connection.execute(
                "SELECT record_sha256 FROM ledger_entries ORDER BY ledger_sequence DESC LIMIT 1"
            ).fetchone()
            previous_sha256 = "" if previous is None else str(previous["record_sha256"])
            for entry in new_entries:
                self._connection.execute(
                    """
                    INSERT INTO ledger_entries(
                        entry_id, occurred_at_ns, record_json, record_sha256, previous_sha256
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        entry.entry_id,
                        entry.occurred_at_ns,
                        canonical_json(entry.canonical_dict()),
                        entry.sha256(),
                        previous_sha256,
                    ),
                )
                previous_sha256 = entry.sha256()
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        self._ledger = candidate
        return tuple(results)

    def reverse(
        self,
        entry_id: str,
        *,
        reversal_id: str,
        occurred_at_ns: int,
        description: str | None = None,
    ) -> JournalEntry:
        self._ensure_open()
        if any(entry.reversal_of == entry_id for entry in self._ledger.entries()):
            raise InvariantViolation(f"JOURNAL_ENTRY_ALREADY_REVERSED:{entry_id}")
        original = next(
            (entry for entry in self._ledger.entries() if entry.entry_id == entry_id),
            None,
        )
        if original is None:
            raise InvariantViolation(f"UNKNOWN_JOURNAL_ENTRY:{entry_id}")
        reversal = JournalEntry(
            entry_id=reversal_id,
            occurred_at_ns=occurred_at_ns,
            description=description or f"Reverse {entry_id}",
            postings=tuple(
                Posting(posting.account, posting.side.opposite(), posting.amount)
                for posting in original.postings
            ),
            reversal_of=entry_id,
        )
        self.post(reversal)
        return reversal

    def entries(self) -> tuple[JournalEntry, ...]:
        self._ensure_open()
        return self._ledger.entries()

    def balance(self, account: str, currency: str) -> Money:
        self._ensure_open()
        return self._ledger.balance(account, currency)

    def sha256(self) -> str:
        self._ensure_open()
        return self._ledger.sha256()

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def __enter__(self) -> "DurableLedger":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
