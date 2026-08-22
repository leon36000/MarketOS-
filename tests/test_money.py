from __future__ import annotations

from decimal import Decimal
import unittest

from marketos.errors import InvariantViolation
from marketos.money import Money, Price, Quantity, RoundingPolicy


class MoneyTests(unittest.TestCase):
    def test_float_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "FLOAT_FORBIDDEN"):
            Money.from_decimal("USD", 1.25)  # type: ignore[arg-type]
        with self.assertRaisesRegex(InvariantViolation, "FLOAT_FORBIDDEN"):
            Quantity.parse(1.5)  # type: ignore[arg-type]

    def test_exact_arithmetic_requires_same_currency(self) -> None:
        left = Money.from_decimal("USD", "10.25")
        right = Money.from_decimal("USD", Decimal("0.75"))
        self.assertEqual((left + right).minor_units, 1100)
        self.assertEqual((left - right).to_decimal(), Decimal("9.50"))
        with self.assertRaisesRegex(InvariantViolation, "CURRENCY_MISMATCH"):
            _ = left + Money.from_decimal("CAD", "1.00")

    def test_extra_precision_requires_explicit_rounding(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "ROUNDING_REQUIRED"):
            Money.from_decimal("USD", "1.005")
        rounded = Money.from_decimal("USD", "1.005", rounding=RoundingPolicy.HALF_UP)
        self.assertEqual(rounded.to_decimal(), Decimal("1.01"))

    def test_quantity_negative_and_positive_contracts(self) -> None:
        self.assertEqual(Quantity.parse("0").value, Decimal("0"))
        with self.assertRaisesRegex(InvariantViolation, "NEGATIVE_QUANTITY"):
            Quantity.parse("-0.01")
        with self.assertRaisesRegex(InvariantViolation, "POSITIVE_QUANTITY_REQUIRED"):
            Quantity.positive("0")

    def test_price_requires_tick_alignment(self) -> None:
        price = Price.parse("USD", "10.125", tick_size="0.005")
        self.assertEqual(price.value, Decimal("10.125"))
        with self.assertRaisesRegex(InvariantViolation, "PRICE_NOT_TICK_ALIGNED"):
            Price.parse("USD", "10.123", tick_size="0.005")

    def test_notional_is_exact_and_rounding_is_explicit(self) -> None:
        price = Price.parse("USD", "12.345", tick_size="0.001")
        quantity = Quantity.positive("3")
        with self.assertRaisesRegex(InvariantViolation, "ROUNDING_REQUIRED"):
            price.notional(quantity)
        money = price.notional(quantity, rounding=RoundingPolicy.HALF_EVEN)
        self.assertEqual(money.to_decimal(), Decimal("37.04"))


if __name__ == "__main__":
    unittest.main()
