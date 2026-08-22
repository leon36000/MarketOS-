from __future__ import annotations

from decimal import Decimal
import unittest

from marketos.errors import InvariantViolation
from marketos.events import EventEnvelope, EventKind, sort_events
from marketos.money import Money, Quantity
from marketos.replay import ReplayCheckpoint, ReplayConfig, ReplayEngine, ReplayStatus
from marketos.risk import RiskLimits
from marketos.time import EventTime


class ReplayTests(unittest.TestCase):
    def limits(self) -> RiskLimits:
        return RiskLimits(
            currency="USD",
            allowed_instruments=frozenset({"AAPL"}),
            max_order_notional=Money.from_decimal("USD", "100000"),
            max_gross_notional=Money.from_decimal("USD", "100000"),
            max_position_quantity=Quantity.positive("1000"),
            max_data_age_ns=1000,
            max_clock_sync_age_ns=1000,
            max_clock_error_ns=10,
        )

    def engine(self, *, max_events: int | None = None, knowledge_cutoff_ns: int | None = None) -> ReplayEngine:
        return ReplayEngine(
            config=ReplayConfig(
                run_id="run-1",
                base_currency="USD",
                initial_cash=Money.from_decimal("USD", "1000"),
                fee_bps=Decimal("10"),
                slippage_bps=Decimal("0"),
                max_events=max_events,
                knowledge_cutoff_ns=knowledge_cutoff_ns,
            ),
            risk_limits=self.limits(),
        )

    def event(self, event_id: str, kind: EventKind, available: int, sequence: int, payload: dict) -> EventEnvelope:
        return EventEnvelope(
            event_id=event_id,
            kind=kind,
            time=EventTime(available - 5, available, available, available),
            source_id="fixture",
            source_priority=1,
            source_sequence=sequence,
            schema_version="1",
            payload=payload,
        )

    def events(self) -> list[EventEnvelope]:
        return [
            self.event(
                "quote-1",
                EventKind.MARKET_SNAPSHOT,
                100,
                1,
                {"instrument_id": "AAPL", "currency": "USD", "bid": "99", "ask": "100", "bid_size": "100", "ask_size": "100", "tick_size": "0.01"},
            ),
            self.event(
                "buy",
                EventKind.ORDER_INTENT,
                110,
                2,
                {"intent_id": "buy", "client_order_id": "c-buy", "idempotency_key": "i-buy", "instrument_id": "AAPL", "side": "BUY", "quantity": "5", "order_type": "MARKET", "time_in_force": "IOC", "created_at_ns": 100, "valid_from_ns": 100, "expires_at_ns": 1000, "strategy_version": "s@1", "config_sha256": "a" * 64, "mode": "PAPER"},
            ),
            self.event(
                "quote-2",
                EventKind.MARKET_SNAPSHOT,
                200,
                3,
                {"instrument_id": "AAPL", "currency": "USD", "bid": "110", "ask": "111", "bid_size": "100", "ask_size": "100", "tick_size": "0.01"},
            ),
            self.event(
                "sell",
                EventKind.ORDER_INTENT,
                210,
                4,
                {"intent_id": "sell", "client_order_id": "c-sell", "idempotency_key": "i-sell", "instrument_id": "AAPL", "side": "SELL", "quantity": "5", "order_type": "MARKET", "time_in_force": "IOC", "created_at_ns": 200, "valid_from_ns": 200, "expires_at_ns": 1000, "strategy_version": "s@1", "config_sha256": "a" * 64, "mode": "PAPER"},
            ),
        ]

    def test_input_order_does_not_change_result(self) -> None:
        events = self.events()
        forward = self.engine().run(events)
        shuffled = self.engine().run([events[3], events[1], events[0], events[2]])
        self.assertEqual(forward.status, ReplayStatus.COMPLETE)
        self.assertEqual(forward.fingerprint, shuffled.fingerprint)
        self.assertEqual(forward.portfolio.cash.to_decimal(), Decimal("1048.95"))

    def test_repeated_run_has_identical_fingerprint(self) -> None:
        first = self.engine().run(self.events())
        second = self.engine().run(self.events())
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.reports, second.reports)

    def test_checkpoint_json_roundtrip_and_resume_match_full_run(self) -> None:
        ordered = list(sort_events(self.events()))
        engine = self.engine()
        checkpoint = engine.checkpoint(ordered, after_events=2)
        restored = ReplayCheckpoint.from_json(checkpoint.to_json())
        resumed = engine.resume(restored, ordered[2:])
        full = engine.run(ordered)
        self.assertEqual(resumed.fingerprint, full.fingerprint)
        self.assertEqual(resumed.portfolio.sha256(), full.portfolio.sha256())

    def test_max_event_limit_stops_without_false_completion(self) -> None:
        result = self.engine(max_events=1).run(self.events())
        self.assertEqual(result.status, ReplayStatus.STOPPED_LIMIT)
        self.assertEqual(result.events_processed, 1)
        self.assertFalse(result.reports)

    def test_knowledge_cutoff_rejects_future_available_event(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "EVENT_AFTER_KNOWLEDGE_CUTOFF"):
            self.engine(knowledge_cutoff_ns=150).run(self.events())


if __name__ == "__main__":
    unittest.main()
