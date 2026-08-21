from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from marketos.authoritative_books import DurableLedger
from marketos.errors import ExecutionStateChanged, InvariantViolation
from marketos.ledger import JournalEntry, Posting, PostingSide
from marketos.money import Money


class C13ExecutionTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "execution.sqlite"

    @staticmethod
    def funding_entry(entry_id: str, amount: str = "100.00") -> JournalEntry:
        money = Money.from_decimal("USD", amount)
        return JournalEntry(
            entry_id=entry_id,
            occurred_at_ns=100,
            description="fund",
            postings=(
                Posting("asset:cash:USD", PostingSide.DEBIT, money),
                Posting("equity:capital:USD", PostingSide.CREDIT, money),
            ),
        )

    def test_expected_head_is_checked_before_execution_body(self) -> None:
        first = DurableLedger(self.path)
        second = DurableLedger(self.path)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        book = first.authoritative_book(base_currency="USD")
        book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
        expected = second.sha256()
        self.assertNotEqual(first.sha256(), expected)

        with self.assertRaises(ExecutionStateChanged):
            with second.execution_transaction(expected):
                self.fail("a stale execution must not enter its commit body")

    def test_successful_execution_transaction_persists_book_and_checkpoint(self) -> None:
        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund(
                "fund-1",
                Money.from_decimal("USD", "100.00"),
                occurred_at_ns=100,
            )
            expected = ledger.sha256()
            with ledger.execution_transaction(expected):
                book.fund(
                    "fund-2",
                    Money.from_decimal("USD", "1.00"),
                    occurred_at_ns=200,
                )
                ledger.checkpoint("checkpoint-2", book, captured_at_ns=300)
            self.assertEqual(
                tuple(entry.entry_id for entry in ledger.entries()),
                ("fund-1", "fund-2"),
            )
            self.assertEqual(ledger.latest_checkpoint().checkpoint_id, "checkpoint-2")

        with DurableLedger(self.path) as reopened:
            self.assertEqual(
                tuple(entry.entry_id for entry in reopened.entries()),
                ("fund-1", "fund-2"),
            )
            self.assertEqual(reopened.latest_checkpoint().checkpoint_id, "checkpoint-2")

    def test_rollback_restores_ledger_book_checkpoint_and_anchor(self) -> None:
        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund(
                "fund-1",
                Money.from_decimal("USD", "100.00"),
                occurred_at_ns=100,
            )
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=150)
            entries_before = ledger.entries()
            snapshot_before = book.snapshot()
            checkpoints_before = (ledger.latest_checkpoint(),)
            anchor_before = ledger.anchor_path.read_bytes()

            with self.assertRaisesRegex(RuntimeError, "force rollback"):
                with ledger.execution_transaction(ledger.sha256()):
                    book.fund(
                        "fund-2",
                        Money.from_decimal("USD", "1.00"),
                        occurred_at_ns=200,
                    )
                    ledger.checkpoint("checkpoint-2", book, captured_at_ns=250)
                    raise RuntimeError("force rollback")

            self.assertEqual(ledger.entries(), entries_before)
            self.assertEqual(book.snapshot(), snapshot_before)
            self.assertEqual((ledger.latest_checkpoint(),), checkpoints_before)
            self.assertEqual(ledger.anchor_path.read_bytes(), anchor_before)

    def test_missing_anchor_on_nonempty_ledger_fails_closed(self) -> None:
        with DurableLedger(self.path) as ledger:
            ledger.post(self.funding_entry("fund-1"))
            ledger.anchor_path.unlink()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)


if __name__ == "__main__":
    unittest.main()
