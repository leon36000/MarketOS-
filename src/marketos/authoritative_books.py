"""Durable paper/shadow book boundaries for the first C13 implementation slice."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterable, Mapping

from .canonical import canonical_json, canonical_sha256
from .errors import DuplicateConflict, InvariantViolation
from .ledger import JournalEntry, Ledger, Posting, PostingSide
from .money import Money, Quantity
from .orders import ExecutionMode
from .portfolio import PortfolioBook, PortfolioSnapshot, Position
from .risk import RiskAction, RiskDecision


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
    live_trading_state: str = "HARD_LOCKED"

    def canonical_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "intent_id": self.intent_id,
            "reasons": self.reasons,
            "upstream_decision_sha256": self.upstream_decision_sha256,
            "reconciliation_sha256": self.reconciliation_sha256,
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
        self._load()
        self._verify_heads(self._ledger.entries(), self._ledger)
        self._load_checkpoints()

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
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        self._ledger = candidate
        return True

    def post_many(self, entries: Iterable[JournalEntry]) -> tuple[bool, ...]:
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
            running = self._ledger.clone()
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

    def checkpoint(
        self,
        checkpoint_id: str,
        book: PortfolioBook,
        *,
        captured_at_ns: int,
    ) -> bool:
        self._ensure_open()
        if not isinstance(book, PortfolioBook) or book.ledger is not self:
            raise InvariantViolation("INVALID_BOOK_CHECKPOINT_SOURCE")
        snapshot = book.snapshot()
        if snapshot.ledger_sha256 != self.sha256():
            raise InvariantViolation("CHECKPOINT_LEDGER_MISMATCH")
        checkpoint = BookCheckpoint(checkpoint_id, captured_at_ns, snapshot)
        existing = next(
            (item for item in self._checkpoints if item.checkpoint_id == checkpoint_id),
            None,
        )
        if existing is not None:
            if existing.sha256() != checkpoint.sha256():
                raise DuplicateConflict(
                    f"BOOK_CHECKPOINT_ID_CONFLICT:{checkpoint_id}"
                )
            return False
        record_json = canonical_json(checkpoint.canonical_dict())
        record_sha256 = checkpoint.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
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
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        self._checkpoints.append(checkpoint)
        return True

    def latest_checkpoint(self) -> BookCheckpoint | None:
        self._ensure_open()
        return self._checkpoints[-1] if self._checkpoints else None

    def verify(self) -> bool:
        self._ensure_open()
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
        if candidate.sha256() != self._ledger.sha256():
            raise InvariantViolation("JOURNAL_INTEGRITY_FAILURE")
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
    return BookReconciliation(
        status=(
            ReconciliationStatus.RECONCILED
            if not reasons
            else ReconciliationStatus.DIVERGENT
        ),
        journal_sha256=journal_sha256,
        book_sha256=book_sha256,
        expected_sha256=expected_sha256,
        reasons=tuple(reasons),
    )


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
            expected = canonical_sha256(
                {
                    "status": reconciliation.status,
                    "journal_sha256": reconciliation.journal_sha256,
                    "book_sha256": reconciliation.book_sha256,
                    "reasons": reconciliation.reasons,
                }
            )
            return expected == reconciliation.expected_sha256
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
    ) -> C13GateDecision:
        payload = {
            "action": action,
            "intent_id": intent_id,
            "reasons": reasons,
            "upstream_decision_sha256": upstream_decision_sha256,
            "reconciliation_sha256": reconciliation_sha256,
            "live_trading_state": "HARD_LOCKED",
        }
        return C13GateDecision(
            action=action,
            intent_id=intent_id,
            reasons=reasons,
            upstream_decision_sha256=upstream_decision_sha256,
            reconciliation_sha256=reconciliation_sha256,
            decision_sha256=canonical_sha256(payload),
            live_trading_state="HARD_LOCKED",
        )

    def evaluate(
        self,
        decision: RiskDecision,
        reconciliation: BookReconciliation,
        mode: ExecutionMode | str,
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
        if decision_valid:
            if decision.action is not RiskAction.ALLOW:
                reasons.append("UPSTREAM_NO_TRADE")
            if not self._decision_is_intact(decision):
                reasons.append("UPSTREAM_DECISION_INTEGRITY_FAILURE")
            if decision.live_trading_state != self.LIVE_TRADING_STATE:
                reasons.append("LIVE_TRADING_LOCK_WEAKENED")
        if reconciliation_valid:
            if reconciliation.status is not ReconciliationStatus.RECONCILED:
                reasons.append("BOOKS_UNRECONCILED")
            if not self._reconciliation_is_intact(reconciliation):
                reasons.append("RECONCILIATION_INTEGRITY_FAILURE")
        reasons_tuple = tuple(reasons)
        return self._build_decision(
            action=RiskAction.NO_TRADE if reasons_tuple else RiskAction.ALLOW,
            intent_id=decision.intent_id if decision_valid else "",
            reasons=reasons_tuple,
            upstream_decision_sha256=(decision.decision_sha256 if decision_valid else ""),
            reconciliation_sha256=(
                reconciliation.sha256() if reconciliation_valid else ""
            ),
        )
