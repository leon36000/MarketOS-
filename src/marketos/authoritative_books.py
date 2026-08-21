"""Durable paper/shadow book boundaries for the first C13 implementation slice."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import os
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
from typing import Any, Iterable, Mapping

from .canonical import canonical_json, canonical_sha256
from .errors import DuplicateConflict, ExecutionStateChanged, InvariantViolation
from .ledger import JournalEntry, Ledger, Posting, PostingSide
from .money import Money, Price, Quantity
from .orders import ExecutionMode
from .portfolio import PortfolioBook, PortfolioSnapshot, Position, TradeApplication
from .risk import RiskAction, RiskDecision


_RECONCILIATION_PROVENANCE = object()


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


def _money_from_data(value: Any, code: str) -> Money:
    data = _mapping(value, code)
    return Money(str(data["currency"]), int(data["minor_units"]))


def _snapshot_from_data(value: Any) -> PortfolioSnapshot:
    data = _mapping(value, "INVALID_BOOK_SNAPSHOT")
    positions = tuple(
        Position(
            instrument_id=str(position["instrument_id"]),
            quantity=Quantity.parse(
                _mapping(position["quantity"], "INVALID_POSITION_QUANTITY")["value"]
            ),
            average_cost=Decimal(str(position["average_cost"])),
            currency=str(position["currency"]),
        )
        for position in data["positions"]
    )
    return PortfolioSnapshot(
        base_currency=str(data["base_currency"]),
        cash=_money_from_data(data["cash"], "INVALID_BOOK_CASH"),
        positions=positions,
        realized_pnl=_money_from_data(data["realized_pnl"], "INVALID_BOOK_PNL"),
        ledger_sha256=str(data["ledger_sha256"]),
    )


class ReconciliationStatus(str, Enum):
    RECONCILED = "RECONCILED"
    DIVERGENT = "DIVERGENT"


@dataclass(frozen=True, slots=True)
class BookCheckpoint:
    checkpoint_id: str
    captured_at_ns: int
    snapshot: PortfolioSnapshot

    def __post_init__(self) -> None:
        if not self.checkpoint_id.strip():
            raise InvariantViolation("MISSING_BOOK_CHECKPOINT_ID")
        if (
            isinstance(self.captured_at_ns, bool)
            or not isinstance(self.captured_at_ns, int)
            or self.captured_at_ns < 0
        ):
            raise InvariantViolation("INVALID_BOOK_CHECKPOINT_TIME")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "captured_at_ns": self.captured_at_ns,
            "snapshot": self.snapshot,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class BookReconciliation:
    status: ReconciliationStatus
    journal_sha256: str
    book_sha256: str
    expected_sha256: str
    reasons: tuple[str, ...]
    _provenance: object = field(default=None, init=False, repr=False, compare=False)
    _source_ledger: Any = field(default=None, init=False, repr=False, compare=False)
    _source_checkpoint_sha256: str | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _source_snapshot: PortfolioSnapshot | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "journal_sha256": self.journal_sha256,
            "book_sha256": self.book_sha256,
            "expected_sha256": self.expected_sha256,
            "reasons": self.reasons,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class C13GateDecision:
    action: RiskAction
    intent_id: str
    reasons: tuple[str, ...]
    upstream_decision_sha256: str
    reconciliation_sha256: str
    decision_sha256: str
    portfolio_snapshot_sha256: str = ""
    ledger_head_sha256: str = ""
    market_view_sha256: str = ""
    live_trading_state: str = "HARD_LOCKED"

    def canonical_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "intent_id": self.intent_id,
            "reasons": self.reasons,
            "upstream_decision_sha256": self.upstream_decision_sha256,
            "reconciliation_sha256": self.reconciliation_sha256,
            "portfolio_snapshot_sha256": self.portfolio_snapshot_sha256,
            "ledger_head_sha256": self.ledger_head_sha256,
            "market_view_sha256": self.market_view_sha256,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


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
        or entry.occurred_at_ns != int(row["occurred_at_ns"])
    ):
        raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
    return entry


class AuthoritativePortfolioBook(PortfolioBook):
    """PortfolioBook whose mutations carry the C13 source capability."""

    def __init__(self, *, base_currency: str, ledger: "DurableLedger") -> None:
        super().__init__(base_currency=base_currency, ledger=ledger)
        self._last_book_ledger_sha256 = ledger.sha256()

    @property
    def _durable_ledger(self) -> "DurableLedger":
        if not isinstance(self.ledger, DurableLedger):
            raise InvariantViolation("INVALID_BOOK_CHECKPOINT_SOURCE")
        return self.ledger

    def fund(self, entry_id: str, amount: Money, *, occurred_at_ns: int) -> bool:
        with self._durable_ledger._book_operation(self):
            inserted = super().fund(entry_id, amount, occurred_at_ns=occurred_at_ns)
            self._last_book_ledger_sha256 = self._durable_ledger.sha256()
            return inserted

    def buy(
        self,
        trade_id: str,
        instrument_id: str,
        quantity: Quantity,
        price: Price,
        fee: Money,
        *,
        occurred_at_ns: int,
    ) -> TradeApplication:
        with self._durable_ledger._book_operation(self):
            result = super().buy(
                trade_id,
                instrument_id,
                quantity,
                price,
                fee,
                occurred_at_ns=occurred_at_ns,
            )
            self._last_book_ledger_sha256 = self._durable_ledger.sha256()
            return result

    def sell(
        self,
        trade_id: str,
        instrument_id: str,
        quantity: Quantity,
        price: Price,
        fee: Money,
        *,
        occurred_at_ns: int,
    ) -> TradeApplication:
        with self._durable_ledger._book_operation(self):
            result = super().sell(
                trade_id,
                instrument_id,
                quantity,
                price,
                fee,
                occurred_at_ns=occurred_at_ns,
            )
            self._last_book_ledger_sha256 = self._durable_ledger.sha256()
            return result

    def _restore_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Restore only a snapshot bound to this book and its current ledger head."""
        if not isinstance(snapshot, PortfolioSnapshot):
            raise InvariantViolation("INVALID_BOOK_ROLLBACK_SNAPSHOT")
        if snapshot.base_currency != self.base_currency:
            raise InvariantViolation("BOOK_ROLLBACK_CURRENCY_MISMATCH")
        current_sha256 = self._durable_ledger.sha256()
        if snapshot.ledger_sha256 != current_sha256:
            raise InvariantViolation("BOOK_ROLLBACK_LEDGER_MISMATCH")
        self._positions = {
            position.instrument_id: position for position in snapshot.positions
        }
        self._realized = snapshot.realized_pnl
        self._last_book_ledger_sha256 = snapshot.ledger_sha256


class DurableLedger:
    """SQLite-backed append-only wrapper around the exact in-memory ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.anchor_path = self.path.with_name(self.path.name + ".anchor.json")
        self._closed = False
        self._authoritative_book: AuthoritativePortfolioBook | None = None
        self._book_operation_owner: AuthoritativePortfolioBook | None = None
        self._book_tainted = False
        self._lock = threading.RLock()
        self._execution_transaction_active = False
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
            CREATE TABLE IF NOT EXISTS ledger_heads (
                head_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_entry_count INTEGER NOT NULL,
                head_record_sha256 TEXT NOT NULL,
                head_ledger_sha256 TEXT NOT NULL,
                previous_head_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS ledger_heads_no_update
            BEFORE UPDATE ON ledger_heads
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER_HEAD');
            END;
            CREATE TRIGGER IF NOT EXISTS ledger_heads_no_delete
            BEFORE DELETE ON ledger_heads
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER_HEAD');
            END;
            CREATE TABLE IF NOT EXISTS book_checkpoints (
                checkpoint_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                checkpoint_id TEXT NOT NULL UNIQUE,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                previous_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS book_checkpoints_no_update
            BEFORE UPDATE ON book_checkpoints
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_BOOK_CHECKPOINT');
            END;
            CREATE TRIGGER IF NOT EXISTS book_checkpoints_no_delete
            BEFORE DELETE ON book_checkpoints
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_BOOK_CHECKPOINT');
            END;
            """
        )
        self._ledger = Ledger()
        self._checkpoints: list[BookCheckpoint] = []
        if not self.anchor_path.exists():
            entry_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
            )
            if entry_count:
                self._connection.close()
                self._closed = True
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            self._write_anchor(Ledger())
        self._load()
        self._load_checkpoints()

    def _ensure_open(self) -> None:
        if self._closed:
            raise InvariantViolation("DURABLE_LEDGER_CLOSED")

    @contextmanager
    def _book_operation(self, book: AuthoritativePortfolioBook):
        with self._lock:
            self._ensure_open()
            if self._authoritative_book is not book:
                raise InvariantViolation("INVALID_BOOK_CHECKPOINT_SOURCE")
            if self._book_tainted:
                raise InvariantViolation("BOOK_SOURCE_TAINTED")
            current_sha256 = (
                self._ledger.sha256()
                if self._execution_transaction_active
                else self._read_ledger().sha256()
            )
            if book._last_book_ledger_sha256 != current_sha256:
                self._book_tainted = True
                raise InvariantViolation("BOOK_SOURCE_TAINTED")
            if self._book_operation_owner is not None:
                raise InvariantViolation("BOOK_OPERATION_REENTRANT")
            self._book_operation_owner = book
            try:
                yield
            finally:
                self._book_operation_owner = None

    def authoritative_book(self, *, base_currency: str) -> AuthoritativePortfolioBook:
        """Create the only checkpoint-capable book for a fresh durable ledger."""
        self._ensure_open()
        if self._authoritative_book is not None:
            if self._authoritative_book.base_currency != base_currency.upper():
                raise InvariantViolation("BOOK_CURRENCY_MISMATCH")
            return self._authoritative_book
        if self._ledger.entries():
            raise InvariantViolation("BOOK_RECONSTRUCTION_REQUIRED")
        self._authoritative_book = AuthoritativePortfolioBook(
            base_currency=base_currency,
            ledger=self,
        )
        return self._authoritative_book

    def _anchor_payload(self, ledger: Ledger) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM ledger_heads ORDER BY head_sequence DESC LIMIT 1"
        ).fetchone()
        return {
            "head_sequence": 0 if row is None else int(row["head_sequence"]),
            "ledger_entry_count": len(ledger.entries()),
            "head_record_sha256": "" if row is None else str(row["head_record_sha256"]),
            "head_ledger_sha256": ledger.sha256(),
        }

    def _write_anchor(self, ledger: Ledger) -> None:
        payload = self._anchor_payload(ledger)
        envelope = {
            **payload,
            "anchor_sha256": canonical_sha256(payload),
        }
        self._replace_anchor_bytes(canonical_json(envelope).encode("utf-8"))

    def _replace_anchor_bytes(self, content: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.anchor_path.parent,
                prefix=f".{self.anchor_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.anchor_path)
            directory_fd = os.open(self.anchor_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _restore_anchor_bytes(self, content: bytes | None) -> None:
        if content is None:
            if self.anchor_path.exists() or self.anchor_path.is_symlink():
                self.anchor_path.unlink()
            directory_fd = os.open(self.anchor_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return
        self._replace_anchor_bytes(content)

    def _verify_anchor(self, ledger: Ledger) -> None:
        if not self.anchor_path.exists():
            raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
        try:
            data = _mapping(
                json.loads(self.anchor_path.read_text(encoding="utf-8")),
                "JOURNAL_INTEGRITY_FAILURE",
            )
            payload = {
                "head_sequence": int(data["head_sequence"]),
                "ledger_entry_count": int(data["ledger_entry_count"]),
                "head_record_sha256": str(data["head_record_sha256"]),
                "head_ledger_sha256": str(data["head_ledger_sha256"]),
            }
            if str(data["anchor_sha256"]) != canonical_sha256(payload):
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if payload != self._anchor_payload(ledger):
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
        except InvariantViolation:
            raise
        except Exception as exc:
            raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE") from exc

    def _load(self) -> None:
        self._ledger = self._read_ledger()

    def _read_ledger(self) -> Ledger:
        previous_sha256 = ""
        expected_sequence = 1
        candidate = Ledger()
        rows = self._connection.execute(
            "SELECT * FROM ledger_entries ORDER BY ledger_sequence"
        ).fetchall()
        for row in rows:
            if int(row["ledger_sequence"]) != expected_sequence:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if str(row["previous_sha256"]) != previous_sha256:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            entry = _entry_from_row(row)
            if not candidate.post(entry):
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            previous_sha256 = str(row["record_sha256"])
            expected_sequence += 1
        self._verify_heads(candidate.entries(), candidate)
        self._verify_anchor(candidate)
        return candidate

    @staticmethod
    def _checkpoint_from_row(row: sqlite3.Row) -> BookCheckpoint:
        try:
            record_json = str(row["record_json"])
            data = _mapping(
                _decode_canonical(json.loads(record_json)),
                "INVALID_BOOK_CHECKPOINT_RECORD",
            )
            checkpoint = BookCheckpoint(
                checkpoint_id=str(data["checkpoint_id"]),
                captured_at_ns=int(data["captured_at_ns"]),
                snapshot=_snapshot_from_data(data["snapshot"]),
            )
        except Exception as exc:
            raise InvariantViolation("BOOK_CHECKPOINT_INTEGRITY_FAILURE") from exc
        if (
            checkpoint.sha256() != str(row["record_sha256"])
            or canonical_json(checkpoint.canonical_dict()) != record_json
            or checkpoint.checkpoint_id != str(row["checkpoint_id"])
        ):
            raise InvariantViolation("BOOK_CHECKPOINT_INTEGRITY_FAILURE")
        return checkpoint

    def _load_checkpoints(self) -> None:
        previous_sha256 = ""
        expected_sequence = 1
        rows = self._connection.execute(
            "SELECT * FROM book_checkpoints ORDER BY checkpoint_sequence"
        ).fetchall()
        for row in rows:
            if int(row["checkpoint_sequence"]) != expected_sequence:
                raise InvariantViolation("BOOK_CHECKPOINT_INTEGRITY_FAILURE")
            if str(row["previous_sha256"]) != previous_sha256:
                raise InvariantViolation("BOOK_CHECKPOINT_INTEGRITY_FAILURE")
            checkpoint = self._checkpoint_from_row(row)
            self._checkpoints.append(checkpoint)
            previous_sha256 = str(row["record_sha256"])
            expected_sequence += 1

    def _refresh_checkpoints(self) -> None:
        self._checkpoints = []
        self._load_checkpoints()

    def _post_in_transaction(self, entry: JournalEntry) -> bool:
        """Append one entry to the already-open SQLite transaction."""
        current = self._ledger
        candidate = current.clone()
        inserted = candidate.post(entry)
        if not inserted:
            self._ledger = current
            return False
        if entry.reversal_of is not None and any(
            existing.reversal_of == entry.reversal_of
            for existing in current.entries()
        ):
            raise InvariantViolation(
                f"JOURNAL_ENTRY_ALREADY_REVERSED:{entry.reversal_of}"
            )
        record_json = canonical_json(entry.canonical_dict())
        record_sha256 = entry.sha256()
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
        previous_head = self._connection.execute(
            "SELECT head_record_sha256 FROM ledger_heads "
            "ORDER BY head_sequence DESC LIMIT 1"
        ).fetchone()
        previous_head_sha256 = (
            "" if previous_head is None else str(previous_head["head_record_sha256"])
        )
        entry_count = int(
            self._connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        )
        self._connection.execute(
            """
            INSERT INTO ledger_heads(
                ledger_entry_count, head_record_sha256,
                head_ledger_sha256, previous_head_sha256
            ) VALUES (?, ?, ?, ?)
            """,
            (
                entry_count,
                record_sha256,
                candidate.sha256(),
                previous_head_sha256,
            ),
        )
        if self._authoritative_book is not None and self._book_operation_owner is None:
            self._book_tainted = True
        self._ledger = candidate
        return True

    def post(self, entry: JournalEntry) -> bool:
        with self._lock:
            self._ensure_open()
            if self._execution_transaction_active:
                return self._post_in_transaction(entry)
            self._connection.execute("BEGIN IMMEDIATE")
            before_ledger = self._ledger
            before_tainted = self._book_tainted
            before_anchor: bytes | None = None
            try:
                current = self._read_ledger()
                self._ledger = current
                before_anchor = self.anchor_path.read_bytes()
                inserted = self._post_in_transaction(entry)
                if inserted:
                    self._write_anchor(self._ledger)
                self._connection.execute("COMMIT")
                return inserted
            except BaseException:
                try:
                    self._connection.execute("ROLLBACK")
                finally:
                    self._ledger = before_ledger
                    self._book_tainted = before_tainted
                    if before_anchor is not None:
                        self._restore_anchor_bytes(before_anchor)
                raise

    def _post_many_in_transaction(
        self,
        pending: tuple[JournalEntry, ...],
    ) -> tuple[bool, ...]:
        current = self._ledger
        candidate = current.clone()
        results: list[bool] = []
        new_entries: list[JournalEntry] = []
        for entry in pending:
            inserted = candidate.post(entry)
            results.append(inserted)
            if inserted:
                if entry.reversal_of is not None and sum(
                    existing.reversal_of == entry.reversal_of
                    for existing in candidate.entries()
                ) > 1:
                    raise InvariantViolation(
                        f"JOURNAL_ENTRY_ALREADY_REVERSED:{entry.reversal_of}"
                    )
                new_entries.append(entry)
        if not new_entries:
            self._ledger = current
            return tuple(results)
        previous = self._connection.execute(
            "SELECT record_sha256 FROM ledger_entries ORDER BY ledger_sequence DESC LIMIT 1"
        ).fetchone()
        previous_sha256 = "" if previous is None else str(previous["record_sha256"])
        previous_head = self._connection.execute(
            "SELECT head_record_sha256 FROM ledger_heads "
            "ORDER BY head_sequence DESC LIMIT 1"
        ).fetchone()
        previous_head_sha256 = (
            "" if previous_head is None else str(previous_head["head_record_sha256"])
        )
        entry_count = int(
            self._connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        )
        running = current.clone()
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
            if not running.post(entry):
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            entry_count += 1
            self._connection.execute(
                """
                INSERT INTO ledger_heads(
                    ledger_entry_count, head_record_sha256,
                    head_ledger_sha256, previous_head_sha256
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    entry_count,
                    entry.sha256(),
                    running.sha256(),
                    previous_head_sha256,
                ),
            )
            previous_head_sha256 = entry.sha256()
        if self._authoritative_book is not None and self._book_operation_owner is None:
            self._book_tainted = True
        self._ledger = candidate
        return tuple(results)

    def post_many(self, entries: Iterable[JournalEntry]) -> tuple[bool, ...]:
        with self._lock:
            self._ensure_open()
            pending = tuple(entries)
            if self._execution_transaction_active:
                return self._post_many_in_transaction(pending)
            self._connection.execute("BEGIN IMMEDIATE")
            before_ledger = self._ledger
            before_tainted = self._book_tainted
            before_anchor: bytes | None = None
            try:
                current = self._read_ledger()
                self._ledger = current
                before_anchor = self.anchor_path.read_bytes()
                results = self._post_many_in_transaction(pending)
                if any(results):
                    self._write_anchor(self._ledger)
                self._connection.execute("COMMIT")
                return results
            except BaseException:
                try:
                    self._connection.execute("ROLLBACK")
                finally:
                    self._ledger = before_ledger
                    self._book_tainted = before_tainted
                    if before_anchor is not None:
                        self._restore_anchor_bytes(before_anchor)
                raise

    def reverse(
        self,
        entry_id: str,
        *,
        reversal_id: str,
        occurred_at_ns: int,
        description: str | None = None,
    ) -> JournalEntry:
        with self._lock:
            self._ensure_open()
            current = (
                self._ledger
                if self._execution_transaction_active
                else self._read_ledger()
            )
            self._ledger = current
            if any(entry.reversal_of == entry_id for entry in current.entries()):
                raise InvariantViolation(f"JOURNAL_ENTRY_ALREADY_REVERSED:{entry_id}")
            original = next(
                (entry for entry in current.entries() if entry.entry_id == entry_id),
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

    def _checkpoint_in_transaction(
        self,
        checkpoint_id: str,
        book: PortfolioBook,
        *,
        captured_at_ns: int,
    ) -> bool:
        if (
            not isinstance(book, AuthoritativePortfolioBook)
            or book is not self._authoritative_book
            or book.ledger is not self
        ):
            raise InvariantViolation("INVALID_BOOK_CHECKPOINT_SOURCE")
        if self._book_tainted:
            raise InvariantViolation("BOOK_SOURCE_TAINTED")
        current = self._ledger
        if book._last_book_ledger_sha256 != current.sha256():
            self._book_tainted = True
            raise InvariantViolation("BOOK_SOURCE_TAINTED")
        snapshot = book.snapshot()
        if snapshot.ledger_sha256 != current.sha256():
            raise InvariantViolation("CHECKPOINT_LEDGER_MISMATCH")
        checkpoint = BookCheckpoint(checkpoint_id, captured_at_ns, snapshot)
        existing_row = self._connection.execute(
            "SELECT * FROM book_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
        if existing_row is not None:
            existing = self._checkpoint_from_row(existing_row)
            if existing.sha256() != checkpoint.sha256():
                raise DuplicateConflict(f"BOOK_CHECKPOINT_ID_CONFLICT:{checkpoint_id}")
            return False
        record_json = canonical_json(checkpoint.canonical_dict())
        record_sha256 = checkpoint.sha256()
        previous = self._connection.execute(
            "SELECT record_sha256 FROM book_checkpoints "
            "ORDER BY checkpoint_sequence DESC LIMIT 1"
        ).fetchone()
        previous_sha256 = "" if previous is None else str(previous["record_sha256"])
        self._connection.execute(
            """
            INSERT INTO book_checkpoints(
                checkpoint_id, record_json, record_sha256, previous_sha256
            ) VALUES (?, ?, ?, ?)
            """,
            (checkpoint_id, record_json, record_sha256, previous_sha256),
        )
        return True

    def checkpoint(
        self,
        checkpoint_id: str,
        book: PortfolioBook,
        *,
        captured_at_ns: int,
    ) -> bool:
        with self._lock:
            self._ensure_open()
            if self._execution_transaction_active:
                return self._checkpoint_in_transaction(
                    checkpoint_id,
                    book,
                    captured_at_ns=captured_at_ns,
                )
            self._connection.execute("BEGIN IMMEDIATE")
            before_ledger = self._ledger
            before_checkpoints = tuple(self._checkpoints)
            before_tainted = self._book_tainted
            try:
                current = self._read_ledger()
                self._ledger = current
                inserted = self._checkpoint_in_transaction(
                    checkpoint_id,
                    book,
                    captured_at_ns=captured_at_ns,
                )
                self._connection.execute("COMMIT")
            except BaseException:
                try:
                    self._connection.execute("ROLLBACK")
                finally:
                    self._ledger = before_ledger
                    self._checkpoints = list(before_checkpoints)
                    self._book_tainted = before_tainted
                raise
            self._refresh_checkpoints()
            return inserted

    @contextmanager
    def execution_transaction(self, expected_ledger_sha256: str):
        """Open the single durable transaction used by authorized execution."""
        with self._lock:
            self._ensure_open()
            if self._execution_transaction_active:
                raise InvariantViolation("EXECUTION_TRANSACTION_REENTRANT")
            before_ledger = self._ledger
            before_checkpoints = tuple(self._checkpoints)
            before_tainted = self._book_tainted
            before_anchor: bytes | None = None
            book_snapshot: PortfolioSnapshot | None = None
            transaction_started = False
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                transaction_started = True
                current = self._read_ledger()
                self._ledger = current
                before_anchor = self.anchor_path.read_bytes()
                if (
                    not isinstance(expected_ledger_sha256, str)
                    or current.sha256() != expected_ledger_sha256
                ):
                    raise ExecutionStateChanged("EXECUTION_STATE_CHANGED")
                self._refresh_checkpoints()
                before_checkpoints = tuple(self._checkpoints)
                if self._authoritative_book is not None:
                    book = self._authoritative_book
                    if book._last_book_ledger_sha256 != current.sha256():
                        self._book_tainted = True
                        raise InvariantViolation("BOOK_SOURCE_TAINTED")
                    book_snapshot = book.snapshot()
                self._execution_transaction_active = True
                yield
                self._write_anchor(self._ledger)
                self._connection.execute("COMMIT")
                transaction_started = False
            except BaseException:
                try:
                    if transaction_started:
                        self._connection.execute("ROLLBACK")
                finally:
                    self._execution_transaction_active = False
                    self._ledger = before_ledger
                    self._checkpoints = list(before_checkpoints)
                    self._book_tainted = before_tainted
                    if before_anchor is not None:
                        self._restore_anchor_bytes(before_anchor)
                    if book_snapshot is not None and self._authoritative_book is not None:
                        self._authoritative_book._restore_snapshot(book_snapshot)
                raise
            finally:
                self._execution_transaction_active = False
            self._refresh_checkpoints()

    def latest_checkpoint(self) -> BookCheckpoint | None:
        with self._lock:
            self._ensure_open()
            if not self._execution_transaction_active:
                self._refresh_checkpoints()
            return self._checkpoints[-1] if self._checkpoints else None

    def verify(self) -> bool:
        with self._lock:
            self._ensure_open()
            candidate = self._ledger if self._execution_transaction_active else self._read_ledger()
            previous_sha256 = ""
            expected_sequence = 1
            checkpoint_rows = self._connection.execute(
                "SELECT * FROM book_checkpoints ORDER BY checkpoint_sequence"
            ).fetchall()
            for row in checkpoint_rows:
                if int(row["checkpoint_sequence"]) != expected_sequence:
                    raise InvariantViolation("BOOK_CHECKPOINT_INTEGRITY_FAILURE")
                if str(row["previous_sha256"]) != previous_sha256:
                    raise InvariantViolation("BOOK_CHECKPOINT_INTEGRITY_FAILURE")
                self._checkpoint_from_row(row)
                previous_sha256 = str(row["record_sha256"])
                expected_sequence += 1
            self._ledger = candidate
            return True

    def _verify_heads(
        self,
        entries: tuple[JournalEntry, ...],
        ledger: Ledger,
    ) -> None:
        rows = self._connection.execute(
            "SELECT * FROM ledger_heads ORDER BY head_sequence"
        ).fetchall()
        if len(rows) != len(entries):
            raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
        previous_head_sha256 = ""
        running = Ledger()
        for index, (row, entry) in enumerate(zip(rows, entries), start=1):
            if int(row["head_sequence"]) != index:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if int(row["ledger_entry_count"]) != index:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if str(row["previous_head_sha256"]) != previous_head_sha256:
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if str(row["head_record_sha256"]) != entry.sha256():
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if not running.post(entry):
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            if str(row["head_ledger_sha256"]) != running.sha256():
                raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
            previous_head_sha256 = str(row["head_record_sha256"])
        if running.sha256() != ledger.sha256():
            raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")

    def entries(self) -> tuple[JournalEntry, ...]:
        with self._lock:
            self._ensure_open()
            return self._ledger.entries()

    def balance(self, account: str, currency: str) -> Money:
        with self._lock:
            self._ensure_open()
            return self._ledger.balance(account, currency)

    def sha256(self) -> str:
        with self._lock:
            self._ensure_open()
            return self._ledger.sha256()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._execution_transaction_active:
                raise InvariantViolation("EXECUTION_TRANSACTION_OPEN")
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "DurableLedger":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def reconcile_book(
    ledger: DurableLedger,
    snapshot: PortfolioSnapshot,
) -> BookReconciliation:
    if not isinstance(ledger, DurableLedger):
        raise InvariantViolation("INVALID_DURABLE_LEDGER")
    if not isinstance(snapshot, PortfolioSnapshot):
        raise InvariantViolation("INVALID_BOOK_SNAPSHOT")
    reasons: list[str] = []
    journal_sha256 = ""
    book_sha256 = snapshot.sha256()
    checkpoint: BookCheckpoint | None = None
    try:
        ledger.verify()
        journal_sha256 = ledger.sha256()
    except InvariantViolation:
        reasons.append("JOURNAL_INTEGRITY_FAILURE")
    if not reasons:
        checkpoint = ledger.latest_checkpoint()
        if checkpoint is None:
            reasons.append("MISSING_BOOK_CHECKPOINT")
        if snapshot.ledger_sha256 != journal_sha256:
            reasons.append("BOOK_LEDGER_HASH_MISMATCH")
        if checkpoint is not None:
            if checkpoint.snapshot.ledger_sha256 != journal_sha256:
                reasons.append("CHECKPOINT_STALE")
            if checkpoint.snapshot != snapshot:
                reasons.append("BOOK_SNAPSHOT_MISMATCH")
    expected_sha256 = canonical_sha256(
        {
            "status": (
                ReconciliationStatus.RECONCILED
                if not reasons
                else ReconciliationStatus.DIVERGENT
            ),
            "journal_sha256": journal_sha256,
            "book_sha256": book_sha256,
            "reasons": tuple(reasons),
        }
    )
    status = ReconciliationStatus.RECONCILED if not reasons else ReconciliationStatus.DIVERGENT
    result = BookReconciliation(
        status=status,
        journal_sha256=journal_sha256,
        book_sha256=book_sha256,
        expected_sha256=expected_sha256,
        reasons=tuple(reasons),
    )
    object.__setattr__(result, "_provenance", _RECONCILIATION_PROVENANCE)
    object.__setattr__(result, "_source_ledger", ledger)
    object.__setattr__(
        result,
        "_source_checkpoint_sha256",
        None if checkpoint is None else checkpoint.sha256(),
    )
    object.__setattr__(result, "_source_snapshot", snapshot)
    return result


class C13RiskGate:
    """Final non-live veto boundary for the C13 book slice."""

    LIVE_TRADING_STATE = "HARD_LOCKED"

    @staticmethod
    def _decision_is_intact(decision: RiskDecision) -> bool:
        try:
            payload = decision.canonical_dict()
            stored = payload.pop("decision_sha256", None)
            return isinstance(stored, str) and canonical_sha256(payload) == stored
        except Exception:
            return False

    @staticmethod
    def _reconciliation_is_intact(reconciliation: BookReconciliation) -> bool:
        try:
            if reconciliation._provenance is not _RECONCILIATION_PROVENANCE:
                return False
            source_ledger = reconciliation._source_ledger
            if not isinstance(source_ledger, DurableLedger):
                return False
            source_ledger.verify()
            if source_ledger.sha256() != reconciliation.journal_sha256:
                return False
            checkpoint = source_ledger.latest_checkpoint()
            current_checkpoint_sha256 = (
                None if checkpoint is None else checkpoint.sha256()
            )
            if current_checkpoint_sha256 != reconciliation._source_checkpoint_sha256:
                return False
            source_snapshot = reconciliation._source_snapshot
            if not isinstance(source_snapshot, PortfolioSnapshot):
                return False
            fresh = reconcile_book(source_ledger, source_snapshot)
            return (
                fresh.status is reconciliation.status
                and fresh.journal_sha256 == reconciliation.journal_sha256
                and fresh.book_sha256 == reconciliation.book_sha256
                and fresh.expected_sha256 == reconciliation.expected_sha256
                and fresh.reasons == reconciliation.reasons
            )
        except Exception:
            return False

    @staticmethod
    def _build_decision(
        *,
        action: RiskAction,
        intent_id: str,
        reasons: tuple[str, ...],
        upstream_decision_sha256: str,
        reconciliation_sha256: str,
        portfolio_snapshot_sha256: str = "",
        ledger_head_sha256: str = "",
        market_view_sha256: str = "",
    ) -> C13GateDecision:
        payload = {
            "action": action,
            "intent_id": intent_id,
            "reasons": reasons,
            "upstream_decision_sha256": upstream_decision_sha256,
            "reconciliation_sha256": reconciliation_sha256,
            "portfolio_snapshot_sha256": portfolio_snapshot_sha256,
            "ledger_head_sha256": ledger_head_sha256,
            "market_view_sha256": market_view_sha256,
            "live_trading_state": "HARD_LOCKED",
        }
        return C13GateDecision(
            action=action,
            intent_id=intent_id,
            reasons=reasons,
            upstream_decision_sha256=upstream_decision_sha256,
            reconciliation_sha256=reconciliation_sha256,
            decision_sha256=canonical_sha256(payload),
            portfolio_snapshot_sha256=portfolio_snapshot_sha256,
            ledger_head_sha256=ledger_head_sha256,
            market_view_sha256=market_view_sha256,
            live_trading_state="HARD_LOCKED",
        )

    def evaluate(
        self,
        decision: RiskDecision,
        reconciliation: BookReconciliation,
        mode: ExecutionMode | str,
        *,
        portfolio_snapshot_sha256: str = "",
        ledger_head_sha256: str = "",
        market_view_sha256: str = "",
    ) -> C13GateDecision:
        reasons: list[str] = []
        decision_valid = isinstance(decision, RiskDecision)
        reconciliation_valid = isinstance(reconciliation, BookReconciliation)
        if not decision_valid:
            reasons.append("INVALID_RISK_DECISION")
        if not reconciliation_valid:
            reasons.append("INVALID_BOOK_RECONCILIATION")
        if not isinstance(mode, ExecutionMode) or mode not in {
            ExecutionMode.PAPER,
            ExecutionMode.SHADOW,
        }:
            reasons.append("EXECUTION_MODE_NOT_ALLOWED")
        binding = (
            portfolio_snapshot_sha256,
            ledger_head_sha256,
            market_view_sha256,
        )
        if any(binding) and not all(binding):
            reasons.append("SOURCE_BINDING_INCOMPLETE")
        if any(
            value
            and (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdefABCDEF" for character in value)
            )
            for value in binding
        ):
            reasons.append("SOURCE_BINDING_INVALID")
        if decision_valid:
            if decision.action is not RiskAction.ALLOW:
                reasons.append("UPSTREAM_NO_TRADE")
            if not self._decision_is_intact(decision):
                reasons.append("UPSTREAM_DECISION_INTEGRITY_FAILURE")
            if decision.live_trading_state != "HARD_LOCKED":
                reasons.append("LIVE_TRADING_LOCK_WEAKENED")
        if reconciliation_valid:
            if reconciliation.status is not ReconciliationStatus.RECONCILED:
                reasons.append("BOOKS_UNRECONCILED")
            if not self._reconciliation_is_intact(reconciliation):
                reasons.append("RECONCILIATION_INTEGRITY_FAILURE")
        reasons_tuple = tuple(reasons)
        intent_id = (
            decision.intent_id
            if decision_valid and isinstance(decision.intent_id, str)
            else ""
        )
        upstream_decision_sha256 = (
            decision.decision_sha256
            if decision_valid and isinstance(decision.decision_sha256, str)
            else ""
        )
        reconciliation_sha256 = ""
        if reconciliation_valid:
            try:
                reconciliation_sha256 = reconciliation.sha256()
            except Exception:
                reconciliation_sha256 = ""
        return self._build_decision(
            action=RiskAction.NO_TRADE if reasons_tuple else RiskAction.ALLOW,
            intent_id=intent_id,
            reasons=reasons_tuple,
            upstream_decision_sha256=upstream_decision_sha256,
            reconciliation_sha256=reconciliation_sha256,
            portfolio_snapshot_sha256=portfolio_snapshot_sha256,
            ledger_head_sha256=ledger_head_sha256,
            market_view_sha256=market_view_sha256,
        )
