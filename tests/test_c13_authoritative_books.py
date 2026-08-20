from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from dataclasses import replace

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.ledger import JournalEntry, Posting, PostingSide
from marketos.money import Money, Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
from marketos.portfolio import PortfolioBook
from marketos.risk import RiskAction, RiskContext, RiskKernel, RiskLimits
from marketos.time import ClockQuality


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


class C13ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"

    def test_checkpoint_survives_reopen_and_reconciles(self) -> None:
        try:
            from marketos.authoritative_books import (
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 reconciliation is not implemented: {exc}")

        with DurableLedger(self.path) as ledger:
            book = PortfolioBook(base_currency="USD", ledger=ledger)
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", snapshot, captured_at_ns=200)

        with DurableLedger(self.path) as reopened:
            result = reconcile_book(reopened, snapshot)
            self.assertEqual(result.status, ReconciliationStatus.RECONCILED)
            self.assertEqual(result.reasons, ())

    def test_snapshot_divergence_is_reported(self) -> None:
        try:
            from marketos.authoritative_books import (
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 reconciliation is not implemented: {exc}")

        with DurableLedger(self.path) as ledger:
            book = PortfolioBook(base_currency="USD", ledger=ledger)
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", snapshot, captured_at_ns=200)
            altered = replace(snapshot, cash=Money.from_decimal("USD", "99.00"))
            result = reconcile_book(ledger, altered)
            self.assertEqual(result.status, ReconciliationStatus.DIVERGENT)
            self.assertIn("BOOK_SNAPSHOT_MISMATCH", result.reasons)

    def test_new_ledger_entry_makes_checkpoint_stale(self) -> None:
        try:
            from marketos.authoritative_books import (
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 reconciliation is not implemented: {exc}")

        with DurableLedger(self.path) as ledger:
            book = PortfolioBook(base_currency="USD", ledger=ledger)
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", snapshot, captured_at_ns=200)
            ledger.post(
                JournalEntry(
                    entry_id="fund-2",
                    occurred_at_ns=300,
                    description="second fund",
                    postings=(
                        Posting(
                            "asset:cash:USD",
                            PostingSide.DEBIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                        Posting(
                            "equity:capital:USD",
                            PostingSide.CREDIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                    ),
                )
            )
            result = reconcile_book(ledger, snapshot)
            self.assertEqual(result.status, ReconciliationStatus.DIVERGENT)
            self.assertIn("CHECKPOINT_STALE", result.reasons)


class C13RiskGateTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from marketos.authoritative_books import (
                C13RiskGate,
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 risk gate is not implemented: {exc}")
        self.C13RiskGate = C13RiskGate
        self.DurableLedger = DurableLedger
        self.ReconciliationStatus = ReconciliationStatus
        self.reconcile_book = reconcile_book
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"
        self.ledger = DurableLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.book = PortfolioBook(base_currency="USD", ledger=self.ledger)
        self.book.fund(
            "fund-1",
            Money.from_decimal("USD", "5000.00"),
            occurred_at_ns=100,
        )
        self.snapshot = self.book.snapshot()
        self.ledger.checkpoint("checkpoint-1", self.snapshot, captured_at_ns=200)
        self.reconciled = reconcile_book(self.ledger, self.snapshot)
        self.kernel = RiskKernel(
            RiskLimits(
                currency="USD",
                allowed_instruments=frozenset({"AAPL"}),
                max_order_notional=Money.from_decimal("USD", "10000"),
                max_gross_notional=Money.from_decimal("USD", "20000"),
                max_position_quantity=Quantity.positive("100"),
                max_data_age_ns=100,
                max_clock_sync_age_ns=500,
                max_clock_error_ns=50,
                allow_short=False,
            )
        )

    def intent(self) -> OrderIntent:
        return OrderIntent(
            intent_id="intent-1",
            client_order_id="client-1",
            idempotency_key="idem-1",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Quantity.positive("10"),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=2_000,
            strategy_version="strategy@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )

    def decision(self, *, cash: str = "5000"):
        return self.kernel.evaluate(
            self.intent(),
            RiskContext(
                now_ns=1_000,
                data_available_at_ns=950,
                books_reconciled=True,
                clock_quality=ClockQuality("chrony", "NTP", 900, 20, 5, "SYNCED"),
                cash=Money.from_decimal("USD", cash),
                current_position=Quantity.parse("0"),
                current_gross_notional=Money.zero("USD"),
                mark_price=Price.parse("USD", "100", tick_size="0.01"),
                estimated_fee=Money.from_decimal("USD", "1"),
            ),
        )

    def test_reconciled_paper_allow_can_pass_gate(self) -> None:
        decision = self.decision()
        result = self.C13RiskGate().evaluate(
            decision,
            self.reconciled,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.ALLOW)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.live_trading_state, "HARD_LOCKED")

    def test_divergent_book_forces_no_trade(self) -> None:
        altered = self.snapshot.__class__(
            base_currency=self.snapshot.base_currency,
            cash=Money.from_decimal("USD", "4999.00"),
            positions=self.snapshot.positions,
            realized_pnl=self.snapshot.realized_pnl,
            ledger_sha256=self.snapshot.ledger_sha256,
        )
        divergent = self.reconcile_book(self.ledger, altered)
        result = self.C13RiskGate().evaluate(
            self.decision(),
            divergent,
            ExecutionMode.SHADOW,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("BOOKS_UNRECONCILED", result.reasons)

    def test_upstream_veto_and_unknown_mode_remain_no_trade(self) -> None:
        result = self.C13RiskGate().evaluate(
            self.decision(cash="0"),
            self.reconciled,
            "LIVE",
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("EXECUTION_MODE_NOT_ALLOWED", result.reasons)
        self.assertIn("UPSTREAM_NO_TRADE", result.reasons)


if __name__ == "__main__":
    unittest.main()
