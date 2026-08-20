from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.ledger import JournalEntry, Posting, PostingSide
from marketos.money import Money


class C13DurableLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"

    @staticmethod
    def entry(entry_id: str, amount: str = "100.00") -> JournalEntry:
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

    def test_reopen_reconstructs_entries_balances_and_hash(self) -> None:
        try:
            from marketos.authoritative_books import DurableLedger
        except ModuleNotFoundError as exc:
            self.fail(f"DurableLedger is not implemented: {exc}")

        original = self.entry("fund-1")
        with DurableLedger(self.path) as ledger:
            self.assertTrue(ledger.post(original))
            expected_sha = ledger.sha256()

        with DurableLedger(self.path) as reopened:
            self.assertEqual(reopened.entries(), (original,))
            self.assertEqual(
                reopened.balance("asset:cash:USD", "USD"),
                Money.from_decimal("USD", "100.00"),
            )
            self.assertEqual(reopened.sha256(), expected_sha)

    def test_identical_duplicate_is_idempotent_and_conflict_does_not_mutate(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = self.entry("fund-1", "100.00")
        conflict = self.entry("fund-1", "101.00")
        with DurableLedger(self.path) as ledger:
            self.assertTrue(ledger.post(first))
            self.assertFalse(ledger.post(first))
            with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
                ledger.post(conflict)
            self.assertEqual(len(ledger.entries()), 1)

    def test_batch_conflict_rolls_back_all_new_entries(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = self.entry("fund-1", "100.00")
        conflict = self.entry("fund-1", "101.00")
        with DurableLedger(self.path) as ledger:
            if not hasattr(ledger, "post_many"):
                self.fail("DurableLedger.post_many is not implemented")
            with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
                ledger.post_many((first, conflict))
            self.assertEqual(ledger.entries(), ())

    def test_reversal_is_persisted_and_reconstructible(self) -> None:
        from marketos.authoritative_books import DurableLedger

        original = self.entry("fund-1", "100.00")
        with DurableLedger(self.path) as ledger:
            ledger.post(original)
            if not hasattr(ledger, "reverse"):
                self.fail("DurableLedger.reverse is not implemented")
            reversal = ledger.reverse(
                "fund-1",
                reversal_id="reversal-1",
                occurred_at_ns=200,
            )
            self.assertEqual(reversal.reversal_of, "fund-1")
        with DurableLedger(self.path) as reopened:
            self.assertEqual(len(reopened.entries()), 2)
            self.assertEqual(
                reopened.balance("asset:cash:USD", "USD"),
                Money.zero("USD"),
            )

    def test_sqlite_update_and_delete_are_rejected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute(
                "UPDATE ledger_entries SET record_json = record_json WHERE entry_id = ?",
                ("fund-1",),
            )
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute(
                "DELETE FROM ledger_entries WHERE entry_id = ?",
                ("fund-1",),
            )

    def test_tampered_record_json_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_update")
        connection.execute(
            "UPDATE ledger_entries SET record_json = ? WHERE entry_id = ?",
            ("{}", "fund-1"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)


if __name__ == "__main__":
    unittest.main()
