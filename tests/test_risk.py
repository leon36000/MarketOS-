from __future__ import annotations

from decimal import Decimal
import unittest

from marketos.money import Money, Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
from marketos.risk import RiskAction, RiskContext, RiskKernel, RiskLimits
from marketos.time import ClockQuality


class RiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = RiskLimits(
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
        self.kernel = RiskKernel(self.limits)

    def intent(self, *, side: OrderSide = OrderSide.BUY, quantity: str = "10", expires_at_ns: int = 2_000) -> OrderIntent:
        return OrderIntent(
            intent_id="intent-1",
            client_order_id="client-1",
            idempotency_key="idem-1",
            instrument_id="AAPL",
            side=side,
            quantity=Quantity.positive(quantity),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=expires_at_ns,
            strategy_version="strategy@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )

    def context(self, **overrides) -> RiskContext:
        values = dict(
            now_ns=1_000,
            data_available_at_ns=950,
            portfolio_snapshot_sha256="b" * 64,
            ledger_head_sha256="c" * 64,
            market_view_sha256="d" * 64,
            clock_quality=ClockQuality("chrony", "NTP", 900, 20, 5, "SYNCED"),
            cash=Money.from_decimal("USD", "5000"),
            current_position=Quantity.parse("0"),
            current_gross_notional=Money.from_decimal("USD", "0"),
            mark_price=Price.parse("USD", "100", tick_size="0.01"),
            estimated_fee=Money.from_decimal("USD", "1"),
        )
        values.update(overrides)
        return RiskContext(**values)

    def assert_denied(self, reason: str, *, intent: OrderIntent | None = None, context: RiskContext | None = None) -> None:
        decision = self.kernel.evaluate(intent or self.intent(), context or self.context())
        self.assertEqual(decision.action, RiskAction.NO_TRADE)
        self.assertIn(reason, decision.reasons)
        self.assertIsNone(decision.approved_quantity)

    def test_valid_paper_order_is_approved_deterministically(self) -> None:
        first = self.kernel.evaluate(self.intent(), self.context())
        second = self.kernel.evaluate(self.intent(), self.context())
        self.assertEqual(first.action, RiskAction.ALLOW)
        self.assertEqual(first.approved_quantity, Quantity.positive("10"))
        self.assertEqual(first.decision_sha256, second.decision_sha256)
        self.assertEqual(first.live_trading_state, "HARD_LOCKED")

    def test_live_execution_mode_does_not_exist(self) -> None:
        with self.assertRaises(ValueError):
            ExecutionMode("LIVE")

    def test_stale_or_future_data_is_denied(self) -> None:
        self.assert_denied("STALE_DATA", context=self.context(data_available_at_ns=899))
        self.assert_denied("FUTURE_DATA", context=self.context(data_available_at_ns=1_001))

    def test_clock_uncertainty_is_denied(self) -> None:
        bad = ClockQuality("chrony", "NTP", 900, 100, 5, "SYNCED")
        self.assert_denied("CLOCK_QUALITY_UNACCEPTABLE", context=self.context(clock_quality=bad))

    def test_source_hashes_are_bound_and_unsupported_instrument_is_denied(self) -> None:
        first = self.kernel.evaluate(self.intent(), self.context())
        altered = self.kernel.evaluate(
            self.intent(),
            self.context(market_view_sha256="f" * 64),
        )
        self.assertNotEqual(first.context_sha256, altered.context_sha256)
        intent = self.intent()
        other = OrderIntent(**{**intent.as_kwargs(), "instrument_id": "MSFT", "intent_id": "intent-2", "client_order_id": "client-2", "idempotency_key": "idem-2"})
        self.assert_denied("INSTRUMENT_NOT_ALLOWED", intent=other)

    def test_expired_intent_is_denied(self) -> None:
        self.assert_denied("INTENT_EXPIRED", intent=self.intent(expires_at_ns=999))

    def test_cash_order_gross_and_position_limits_are_enforced(self) -> None:
        self.assert_denied("INSUFFICIENT_CASH", context=self.context(cash=Money.from_decimal("USD", "500")))
        self.assert_denied("ORDER_NOTIONAL_LIMIT", intent=self.intent(quantity="101"))
        self.assert_denied(
            "GROSS_NOTIONAL_LIMIT",
            context=self.context(current_gross_notional=Money.from_decimal("USD", "19500")),
        )
        self.assert_denied(
            "POSITION_QUANTITY_LIMIT",
            context=self.context(current_position=Quantity.parse("95")),
        )

    def test_sell_without_position_is_denied(self) -> None:
        self.assert_denied("INSUFFICIENT_POSITION", intent=self.intent(side=OrderSide.SELL))


if __name__ == "__main__":
    unittest.main()
