from __future__ import annotations

from decimal import Decimal
import unittest
from uuid import UUID

from marketos.bars import build_trade_bars
from marketos.marketdata import (
    MarketObservation,
    ObservationKind,
    ObservationStatus,
    TradePayload,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.time import EventTime


LISTING_ID = UUID("00000000-0000-0000-0000-000000004100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000004010")


class BarTests(unittest.TestCase):
    @staticmethod
    def rights() -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("non_display", "historical_replay", "derived_data"):
            fields[field] = RightDecision.ALLOW
        return RightsPolicy("bar-rights", fields)

    @staticmethod
    def trade(observation_id: str, sequence: int, event_ns: int, available_ns: int, price: str, size: str) -> MarketObservation:
        return MarketObservation(
            observation_id=observation_id,
            version=1,
            kind=ObservationKind.TRADE,
            status=ObservationStatus.ORIGINAL,
            listing_id=LISTING_ID,
            venue_id=VENUE_ID,
            source_id="fixture",
            channel_id="trades",
            source_sequence=sequence,
            time=EventTime(event_ns, available_ns, available_ns, available_ns),
            raw_content_sha256=(hex(sequence)[2:] * 64)[:64].ljust(64, "0"),
            schema_version="trade@1",
            payload=TradePayload(
                price=Price.parse("USD", price, tick_size="0.01"),
                size=Quantity.positive(size),
                condition_codes=(),
            ),
        )

    def test_bar_is_deterministic_exact_and_has_no_lookahead(self) -> None:
        early = self.trade("early", 1, 10, 20, "100", "2")
        middle = self.trade("middle", 2, 20, 30, "105", "3")
        close = self.trade("close", 3, 90, 95, "102", "1")
        late_arrival = self.trade("late-arrival", 4, 80, 120, "110", "4")

        first = build_trade_bars(
            (close, middle, early, late_arrival),
            interval_ns=100,
            knowledge_time_ns=100,
            rights_policy=self.rights(),
        )
        second = build_trade_bars(
            (early, late_arrival, close, middle),
            interval_ns=100,
            knowledge_time_ns=100,
            rights_policy=self.rights(),
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        bar = first[0]
        self.assertEqual(bar.open.value, Decimal("100"))
        self.assertEqual(bar.high.value, Decimal("105"))
        self.assertEqual(bar.low.value, Decimal("100"))
        self.assertEqual(bar.close.value, Decimal("102"))
        self.assertEqual(bar.volume.value, Decimal("6"))
        self.assertEqual(bar.trade_count, 3)
        self.assertEqual(bar.available_to_strategy_at_ns, 100)
        self.assertEqual(bar.rights_policy_sha256, self.rights().sha256())

        revised = build_trade_bars(
            (early, middle, close, late_arrival),
            interval_ns=100,
            knowledge_time_ns=130,
            rights_policy=self.rights(),
        )
        self.assertEqual(revised[0].high.value, Decimal("110"))
        self.assertEqual(revised[0].volume.value, Decimal("10"))
        self.assertEqual(revised[0].available_to_strategy_at_ns, 120)
        self.assertNotEqual(revised[0].input_root_sha256, bar.input_root_sha256)

    def test_incomplete_bucket_is_not_published(self) -> None:
        trade = self.trade("future-bucket", 1, 110, 120, "100", "1")
        self.assertEqual(
            build_trade_bars(
                (trade,),
                interval_ns=100,
                knowledge_time_ns=150,
                rights_policy=self.rights(),
            ),
            (),
        )
        self.assertEqual(
            len(
                build_trade_bars(
                    (trade,),
                    interval_ns=100,
                    knowledge_time_ns=200,
                    rights_policy=self.rights(),
                )
            ),
            1,
        )

    def test_duplicate_trade_identity_is_rejected(self) -> None:
        trade = self.trade("dup", 1, 10, 20, "100", "1")
        with self.assertRaisesRegex(Exception, "DUPLICATE_TRADE_OBSERVATION"):
            build_trade_bars(
                (trade, trade),
                interval_ns=100,
                knowledge_time_ns=100,
                rights_policy=self.rights(),
            )


if __name__ == "__main__":
    unittest.main()
