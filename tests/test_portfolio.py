from __future__ import annotations

from decimal import Decimal
import unittest

from marketos.errors import InvariantViolation
from marketos.money import Money, Price, Quantity
from marketos.portfolio import PortfolioBook


class PortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = PortfolioBook(base_currency="USD")
        self.book.fund("fund", Money.from_decimal("USD", "1000.00"), occurred_at_ns=1)

    def price(self, value: str) -> Price:
        return Price.parse("USD", value, tick_size="0.01")

    def test_funding_buy_sell_average_cost_and_realized_pnl(self) -> None:
        first = self.book.buy(
            "buy-1", "AAPL", Quantity.positive("10"), self.price("10.00"), Money.from_decimal("USD", "1.00"), occurred_at_ns=2
        )
        second = self.book.buy(
            "buy-2", "AAPL", Quantity.positive("10"), self.price("20.00"), Money.from_decimal("USD", "1.00"), occurred_at_ns=3
        )
        sale = self.book.sell(
            "sell-1", "AAPL", Quantity.positive("5"), self.price("18.00"), Money.from_decimal("USD", "1.00"), occurred_at_ns=4
        )
        self.assertTrue(first.inserted and second.inserted and sale.inserted)
        position = self.book.position("AAPL")
        self.assertEqual(position.quantity.value, Decimal("15"))
        self.assertEqual(position.average_cost, Decimal("15"))
        self.assertEqual(self.book.cash().to_decimal(), Decimal("787.00"))
        self.assertEqual(self.book.realized_pnl().to_decimal(), Decimal("14.00"))
        self.assertEqual(self.book.ledger.balance("asset:inventory:AAPL", "USD").to_decimal(), Decimal("225.00"))

    def test_duplicate_trade_does_not_apply_twice(self) -> None:
        kwargs = dict(
            trade_id="buy-1",
            instrument_id="AAPL",
            quantity=Quantity.positive("10"),
            price=self.price("10.00"),
            fee=Money.from_decimal("USD", "1.00"),
            occurred_at_ns=2,
        )
        first = self.book.buy(**kwargs)
        second = self.book.buy(**kwargs)
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(self.book.position("AAPL").quantity.value, Decimal("10"))
        self.assertEqual(self.book.cash().to_decimal(), Decimal("899.00"))

    def test_insufficient_cash_and_position_are_rejected_without_mutation(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "INSUFFICIENT_CASH"):
            self.book.buy(
                "too-big", "AAPL", Quantity.positive("1000"), self.price("10"), Money.zero("USD"), occurred_at_ns=2
            )
        self.assertEqual(self.book.cash().to_decimal(), Decimal("1000.00"))
        with self.assertRaisesRegex(InvariantViolation, "INSUFFICIENT_POSITION"):
            self.book.sell(
                "short", "AAPL", Quantity.positive("1"), self.price("10"), Money.zero("USD"), occurred_at_ns=3
            )

    def test_currency_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "PORTFOLIO_CURRENCY_MISMATCH"):
            self.book.buy(
                "cad", "SHOP", Quantity.positive("1"), Price.parse("CAD", "100", tick_size="0.01"), Money.zero("CAD"), occurred_at_ns=2
            )


if __name__ == "__main__":
    unittest.main()
