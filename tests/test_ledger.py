from __future__ import annotations

import unittest

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.ledger import JournalEntry, Ledger, Posting, PostingSide
from marketos.money import Money


class LedgerTests(unittest.TestCase):
    def entry(self, entry_id: str, amount: str = "100.00") -> JournalEntry:
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

    def test_unbalanced_entry_is_rejected_per_currency(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "UNBALANCED_JOURNAL_ENTRY"):
            JournalEntry(
                entry_id="bad",
                occurred_at_ns=1,
                description="bad",
                postings=(
                    Posting("asset:cash:USD", PostingSide.DEBIT, Money.from_decimal("USD", "10")),
                    Posting("equity:capital:USD", PostingSide.CREDIT, Money.from_decimal("USD", "9")),
                ),
            )

    def test_identical_duplicate_is_idempotent_but_conflict_is_rejected(self) -> None:
        ledger = Ledger()
        self.assertTrue(ledger.post(self.entry("fund")))
        self.assertFalse(ledger.post(self.entry("fund")))
        with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
            ledger.post(self.entry("fund", "101.00"))
        self.assertEqual(len(ledger.entries()), 1)

    def test_reversal_is_append_only_and_nets_original_balance(self) -> None:
        ledger = Ledger()
        original = self.entry("fund")
        ledger.post(original)
        reversal = ledger.reverse("fund", reversal_id="fund-reversal", occurred_at_ns=200)
        self.assertEqual(len(ledger.entries()), 2)
        self.assertEqual(reversal.reversal_of, "fund")
        self.assertEqual(ledger.balance("asset:cash:USD", "USD"), Money.zero("USD"))
        self.assertEqual(ledger.entries()[0], original)

    def test_balance_is_debit_minus_credit(self) -> None:
        ledger = Ledger()
        ledger.post(self.entry("fund", "250.00"))
        self.assertEqual(ledger.balance("asset:cash:USD", "USD").to_decimal().as_tuple().sign, 0)
        self.assertEqual(ledger.balance("asset:cash:USD", "USD").to_decimal(), Money.from_decimal("USD", "250").to_decimal())
        self.assertEqual(ledger.balance("equity:capital:USD", "USD").minor_units, -25000)


if __name__ == "__main__":
    unittest.main()
