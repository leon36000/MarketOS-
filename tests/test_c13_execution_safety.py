from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from marketos.authoritative_books import DurableLedger
from marketos.errors import ExecutionStateChanged, InvariantViolation
from marketos.ledger import JournalEntry, Posting, PostingSide
from marketos.money import Money
from marketos.paper import MarketSnapshot, PaperBroker
from marketos.portfolio import PortfolioBook
from marketos.risk import RiskContext, RiskKernel, RiskLimits
from marketos.money import Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
from marketos.time import ClockQuality


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


class C13EvidenceBindingTests(unittest.TestCase):
    @staticmethod
    def snapshot(instrument_id: str = "AAPL", bid: str = "99", ask: str = "100") -> MarketSnapshot:
        return MarketSnapshot(
            instrument_id=instrument_id,
            bid=Price.parse("USD", bid, tick_size="0.01"),
            ask=Price.parse("USD", ask, tick_size="0.01"),
            bid_size=Quantity.parse("100"),
            ask_size=Quantity.parse("100"),
            available_at_ns=950,
            source_event_id=f"quote-{instrument_id}",
        )

    @staticmethod
    def intent() -> OrderIntent:
        return OrderIntent(
            intent_id="evidence-intent",
            client_order_id="evidence-client",
            idempotency_key="evidence-idem",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Quantity.positive("1"),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=2_000,
            strategy_version="evidence@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )

    def test_market_snapshot_and_view_are_content_addressed(self) -> None:
        from marketos.paper import MarketView

        execution = self.snapshot()
        mark = self.snapshot("MSFT", "49", "50")
        view = MarketView(execution=execution, marks=(mark,))
        altered = replace(mark, bid=Price.parse("USD", "48", tick_size="0.01"))
        self.assertNotEqual(view.sha256(), MarketView(execution=execution, marks=(altered,)).sha256())

    def test_risk_context_source_hash_changes_decision_evidence(self) -> None:
        context = RiskContext(
            now_ns=1_000,
            data_available_at_ns=950,
            portfolio_snapshot_sha256="b" * 64,
            ledger_head_sha256="c" * 64,
            market_view_sha256="d" * 64,
            clock_quality=ClockQuality("chrony", "NTP", 900, 20, 5, "SYNCED"),
            cash=Money.from_decimal("USD", "1000"),
            current_position=Quantity.parse("0"),
            current_gross_notional=Money.zero("USD"),
            mark_price=Price.parse("USD", "100", tick_size="0.01"),
            estimated_fee=Money.from_decimal("USD", "1"),
        )
        limits = RiskLimits(
            currency="USD",
            allowed_instruments=frozenset({"AAPL"}),
            max_order_notional=Money.from_decimal("USD", "10000"),
            max_gross_notional=Money.from_decimal("USD", "20000"),
            max_position_quantity=Quantity.positive("100"),
            max_data_age_ns=100,
            max_clock_sync_age_ns=500,
            max_clock_error_ns=50,
        )
        first = RiskKernel(limits).evaluate(self.intent(), context)
        altered = RiskKernel(limits).evaluate(
            self.intent(),
            replace(context, market_view_sha256="f" * 64),
        )
        self.assertNotEqual(first.context_sha256, altered.context_sha256)

    def test_direct_paper_broker_submission_is_forbidden(self) -> None:
        book = PortfolioBook(base_currency="USD")
        broker = PaperBroker(
            portfolio=book,
            risk_kernel=RiskKernel(
                RiskLimits(
                    currency="USD",
                    allowed_instruments=frozenset({"AAPL"}),
                    max_order_notional=Money.from_decimal("USD", "10000"),
                    max_gross_notional=Money.from_decimal("USD", "20000"),
                    max_position_quantity=Quantity.positive("100"),
                    max_data_age_ns=100,
                    max_clock_sync_age_ns=500,
                    max_clock_error_ns=50,
                )
            ),
            fee_bps="0",
            slippage_bps="0",
        )
        with self.assertRaisesRegex(InvariantViolation, "PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN"):
            broker.submit(None, now_ns=0, clock_quality=None, books_reconciled=True)


if __name__ == "__main__":
    unittest.main()
