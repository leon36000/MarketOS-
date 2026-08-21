from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from marketos.authoritative_books import DurableLedger
from marketos.errors import DuplicateConflict
from marketos.money import Money, Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderState, OrderType, TimeInForce
from marketos.paper import MarketSnapshot, PaperBroker
from marketos.execution_safety import C13PreTradeEnvelope
from marketos.risk import RiskKernel, RiskLimits
from marketos.time import ClockQuality


class PaperBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.ledger = DurableLedger(Path(self.temp_dir.name) / "paper.sqlite")
        self.addCleanup(self.ledger.close)
        self.book = self.ledger.authoritative_book(base_currency="USD")
        self.book.fund("fund", Money.from_decimal("USD", "1000"), occurred_at_ns=1)
        self.ledger.checkpoint("initial", self.book, captured_at_ns=2)
        limits = RiskLimits(
            currency="USD",
            allowed_instruments=frozenset({"AAPL"}),
            max_order_notional=Money.from_decimal("USD", "100000"),
            max_gross_notional=Money.from_decimal("USD", "100000"),
            max_position_quantity=Quantity.positive("1000"),
            max_data_age_ns=100,
            max_clock_sync_age_ns=500,
            max_clock_error_ns=50,
        )
        self.broker = PaperBroker(
            portfolio=self.book,
            risk_kernel=RiskKernel(limits),
            fee_bps="10",
            slippage_bps="0",
        )
        self.clock = ClockQuality("chrony", "NTP", 900, 10, 0, "SYNCED")
        self.broker.update_market(self.snapshot("99", "100", bid_size="100", ask_size="100", available_at_ns=950))
        self.envelope = C13PreTradeEnvelope(
            broker=self.broker,
            book=self.book,
            ledger=self.ledger,
        )

    def snapshot(self, bid: str, ask: str, *, bid_size: str, ask_size: str, available_at_ns: int) -> MarketSnapshot:
        return MarketSnapshot(
            instrument_id="AAPL",
            bid=Price.parse("USD", bid, tick_size="0.01"),
            ask=Price.parse("USD", ask, tick_size="0.01"),
            bid_size=Quantity.parse(bid_size),
            ask_size=Quantity.parse(ask_size),
            available_at_ns=available_at_ns,
            source_event_id=f"quote-{available_at_ns}",
        )

    def intent(
        self,
        intent_id: str,
        side: OrderSide,
        quantity: str,
        *,
        order_type: OrderType = OrderType.MARKET,
        limit: str | None = None,
        idempotency_key: str | None = None,
    ) -> OrderIntent:
        return OrderIntent(
            intent_id=intent_id,
            client_order_id=f"client-{intent_id}",
            idempotency_key=idempotency_key or f"idem-{intent_id}",
            instrument_id="AAPL",
            side=side,
            quantity=Quantity.positive(quantity),
            order_type=order_type,
            limit_price=None if limit is None else Price.parse("USD", limit, tick_size="0.01"),
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=2_000,
            strategy_version="strategy@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )

    def submit(self, intent: OrderIntent, now_ns: int = 1_000):
        return self.envelope.submit(intent, now_ns=now_ns, clock_quality=self.clock)

    def test_buy_and_sell_update_exact_books_and_pnl(self) -> None:
        buy = self.submit(self.intent("buy", OrderSide.BUY, "5"))
        self.assertEqual(buy.state, OrderState.FILLED)
        self.assertEqual(buy.fills[0].price.value, Decimal("100"))
        self.assertEqual(buy.fills[0].fee.to_decimal(), Decimal("0.50"))
        self.assertEqual(self.book.cash().to_decimal(), Decimal("499.50"))

        self.broker.update_market(self.snapshot("110", "111", bid_size="100", ask_size="100", available_at_ns=1_050))
        sale = self.submit(self.intent("sell", OrderSide.SELL, "5"), now_ns=1_100)
        self.assertEqual(sale.state, OrderState.FILLED)
        self.assertEqual(sale.fills[0].fee.to_decimal(), Decimal("0.55"))
        self.assertEqual(self.book.cash().to_decimal(), Decimal("1048.95"))
        self.assertEqual(self.book.position("AAPL").quantity.value, Decimal("0"))
        self.assertEqual(self.book.realized_pnl().to_decimal(), Decimal("49.45"))

    def test_non_marketable_limit_is_cancelled_without_mutation(self) -> None:
        report = self.submit(
            self.intent("limit", OrderSide.BUY, "1", order_type=OrderType.LIMIT, limit="99.00")
        )
        self.assertEqual(report.state, OrderState.CANCELLED)
        self.assertIn("LIMIT_NOT_MARKETABLE", report.reasons)
        self.assertEqual(self.book.cash().to_decimal(), Decimal("1000.00"))

    def test_partial_fill_is_bounded_by_visible_size(self) -> None:
        self.broker.update_market(self.snapshot("99", "100", bid_size="100", ask_size="3", available_at_ns=960))
        report = self.submit(self.intent("partial", OrderSide.BUY, "5"))
        self.assertEqual(report.state, OrderState.PARTIALLY_FILLED)
        self.assertEqual(report.fills[0].quantity.value, Decimal("3"))
        self.assertEqual(report.remaining_quantity.value, Decimal("2"))

    def test_duplicate_intent_is_idempotent(self) -> None:
        intent = self.intent("dup", OrderSide.BUY, "1")
        first = self.submit(intent)
        cash_after_first = self.book.cash()
        second = self.submit(intent)
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(first.fills, second.fills)
        self.assertEqual(self.book.cash(), cash_after_first)

    def test_conflicting_idempotency_key_is_rejected(self) -> None:
        self.submit(self.intent("one", OrderSide.BUY, "1", idempotency_key="shared"))
        with self.assertRaisesRegex(DuplicateConflict, "IDEMPOTENCY_KEY_CONFLICT"):
            self.submit(self.intent("two", OrderSide.BUY, "2", idempotency_key="shared"))

    def test_risk_denial_does_not_execute(self) -> None:
        report = self.submit(self.intent("too-large", OrderSide.BUY, "100"))
        self.assertEqual(report.state, OrderState.REJECTED)
        self.assertIn("INSUFFICIENT_CASH", report.reasons)
        self.assertFalse(report.fills)
        self.assertEqual(self.book.cash().to_decimal(), Decimal("1000.00"))


if __name__ == "__main__":
    unittest.main()
