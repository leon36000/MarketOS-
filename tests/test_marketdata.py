from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.datafabric import RawEvidenceStore
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.marketdata import (
    IngestionDenied,
    IngestionDisposition,
    MarketDataStore,
    MarketObservation,
    ObservationKind,
    ObservationStatus,
    QualityPolicy,
    QualityState,
    QuotePayload,
    TradePayload,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.time import EventTime


LISTING_ID = UUID("00000000-0000-0000-0000-000000004100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000004010")


class MarketDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-marketdata-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.raw = RawEvidenceStore(self.temp / "raw")
        self.addCleanup(self.raw.close)
        self.store = MarketDataStore(self.temp / "market.sqlite", raw_evidence_store=self.raw)
        self.addCleanup(self.store.close)
        self.quality = QualityPolicy(
            max_future_skew_ns=5,
            max_latency_ns=100,
            crossed_quote_action="QUARANTINE",
            zero_trade_price_action="QUARANTINE",
        )

    @staticmethod
    def rights(*, allow: bool = True) -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        if allow:
            for field in ("storage", "non_display", "historical_replay", "derived_data"):
                fields[field] = RightDecision.ALLOW
        return RightsPolicy("market-rights", fields)

    def raw_sha(self, suffix: str) -> str:
        return self.raw.put(
            f"raw:{suffix}".encode(),
            source_id="fixture-feed",
            retrieved_at_ns=90,
            media_type="application/octet-stream",
            rights_policy_ids=("market-rights",),
        ).content_sha256

    def quote(
        self,
        observation_id: str,
        sequence: int,
        *,
        version: int = 1,
        status: ObservationStatus = ObservationStatus.ORIGINAL,
        bid: str = "99",
        ask: str = "100",
        bid_size: str = "10",
        ask_size: str = "10",
        event_ns: int = 100,
        receive_ns: int = 110,
        available_ns: int = 110,
    ) -> MarketObservation:
        return MarketObservation(
            observation_id=observation_id,
            version=version,
            kind=ObservationKind.QUOTE,
            status=status,
            listing_id=LISTING_ID,
            venue_id=VENUE_ID,
            source_id="fixture-feed",
            channel_id="quotes",
            source_sequence=sequence,
            time=EventTime(event_ns, available_ns, receive_ns, receive_ns),
            raw_content_sha256=self.raw_sha(f"{observation_id}:{version}"),
            schema_version="quote@1",
            payload=QuotePayload(
                bid=Price.parse("USD", bid, tick_size="0.01"),
                ask=Price.parse("USD", ask, tick_size="0.01"),
                bid_size=Quantity.parse(bid_size),
                ask_size=Quantity.parse(ask_size),
            ),
        )

    def trade(
        self,
        observation_id: str,
        sequence: int,
        *,
        event_ns: int = 100,
        receive_ns: int = 110,
        available_ns: int = 110,
        price: str = "100",
        size: str = "2",
    ) -> MarketObservation:
        return MarketObservation(
            observation_id=observation_id,
            version=1,
            kind=ObservationKind.TRADE,
            status=ObservationStatus.ORIGINAL,
            listing_id=LISTING_ID,
            venue_id=VENUE_ID,
            source_id="fixture-feed",
            channel_id="trades",
            source_sequence=sequence,
            time=EventTime(event_ns, available_ns, receive_ns, receive_ns),
            raw_content_sha256=self.raw_sha(observation_id),
            schema_version="trade@1",
            payload=TradePayload(
                price=Price.parse("USD", price, tick_size="0.01"),
                size=Quantity.positive(size),
                condition_codes=(),
            ),
        )

    def test_contiguous_sequence_is_accepted_and_duplicate_is_idempotent(self) -> None:
        first = self.store.ingest(self.quote("q-100", 100), quality_policy=self.quality, rights_policy=self.rights())
        second = self.store.ingest(self.quote("q-101", 101), quality_policy=self.quality, rights_policy=self.rights())
        duplicate = self.store.ingest(self.quote("q-101", 101), quality_policy=self.quality, rights_policy=self.rights())
        self.assertEqual(first.disposition, IngestionDisposition.INSERTED_ACCEPTED)
        self.assertEqual(second.quality_state, QualityState.ACCEPTED)
        self.assertEqual(duplicate.disposition, IngestionDisposition.DUPLICATE)
        self.assertFalse(duplicate.inserted)
        self.assertEqual(len(self.store.stream(LISTING_ID, 0, 200, knowledge_time_ns=200)), 2)

    def test_sequence_gap_and_collision_are_quarantined(self) -> None:
        self.store.ingest(self.quote("q-100", 100), quality_policy=self.quality, rights_policy=self.rights())
        gap = self.store.ingest(self.quote("q-102", 102), quality_policy=self.quality, rights_policy=self.rights())
        self.assertEqual(gap.disposition, IngestionDisposition.INSERTED_QUARANTINED)
        self.assertIn("SEQUENCE_GAP:expected=101:actual=102", gap.reasons)
        collision = self.store.ingest(self.quote("q-other", 100), quality_policy=self.quality, rights_policy=self.rights())
        self.assertEqual(collision.quality_state, QualityState.QUARANTINED)
        self.assertIn("SEQUENCE_COLLISION", collision.reasons)
        accepted = self.store.stream(LISTING_ID, 0, 200, knowledge_time_ns=200)
        self.assertEqual(tuple(item.observation_id for item in accepted), ("q-100",))
        self.assertEqual(len(self.store.quarantine_records()), 2)

    def test_crossed_future_and_excessively_late_observations_are_quarantined(self) -> None:
        crossed = self.store.ingest(
            self.quote("crossed", 1, bid="101", ask="100"),
            quality_policy=self.quality,
            rights_policy=self.rights(),
        )
        self.assertIn("CROSSED_QUOTE", crossed.reasons)
        future = self.store.ingest(
            self.trade("future", 1, event_ns=120, receive_ns=110, available_ns=120),
            quality_policy=self.quality,
            rights_policy=self.rights(),
        )
        self.assertIn("EVENT_TIME_FUTURE_SKEW", future.reasons)
        late = self.store.ingest(
            self.trade("late", 2, event_ns=1, receive_ns=200, available_ns=200),
            quality_policy=self.quality,
            rights_policy=self.rights(),
        )
        self.assertIn("EXCESSIVE_SOURCE_LATENCY", late.reasons)

    def test_correction_and_cancellation_are_latest_known_without_resurrection(self) -> None:
        original = self.quote("q", 1, event_ns=50, receive_ns=60, available_ns=60)
        self.store.ingest(original, quality_policy=self.quality, rights_policy=self.rights())
        correction = self.quote(
            "q",
            2,
            version=2,
            status=ObservationStatus.CORRECTED,
            bid="98",
            ask="99",
            event_ns=50,
            receive_ns=100,
            available_ns=100,
        )
        self.store.ingest(correction, quality_policy=self.quality, rights_policy=self.rights())
        cancelled = self.quote(
            "q",
            3,
            version=3,
            status=ObservationStatus.CANCELLED,
            bid="98",
            ask="99",
            event_ns=50,
            receive_ns=150,
            available_ns=150,
        )
        self.store.ingest(cancelled, quality_policy=self.quality, rights_policy=self.rights())
        self.assertEqual(self.store.effective_as_known("q", knowledge_time_ns=80), original)
        self.assertEqual(self.store.effective_as_known("q", knowledge_time_ns=120), correction)
        self.assertIsNone(self.store.effective_as_known("q", knowledge_time_ns=200))
        self.assertEqual(len(self.store.history("q")), 3)

    def test_denied_rights_or_missing_raw_evidence_never_become_accepted(self) -> None:
        with self.assertRaises(IngestionDenied):
            self.store.ingest(self.quote("denied", 1), quality_policy=self.quality, rights_policy=self.rights(allow=False))

    def test_market_observation_is_immutable(self) -> None:
        observation = self.quote("immutable", 1)
        with self.assertRaises((AttributeError, TypeError)):
            observation.source_sequence = 9

    def test_missing_raw_reference_is_quarantined(self) -> None:
        observation = self.quote("missing", 1)
        object.__setattr__(observation, "raw_content_sha256", "f" * 64)
        result = self.store.ingest(observation, quality_policy=self.quality, rights_policy=self.rights())
        self.assertIn("RAW_EVIDENCE_MISSING_OR_CORRUPT", result.reasons)
        self.assertEqual(result.quality_state, QualityState.QUARANTINED)

    def test_stored_observation_hash_is_verified_on_read(self) -> None:
        self.store.ingest(self.quote("tamper", 1), quality_policy=self.quality, rights_policy=self.rights())
        connection = sqlite3.connect(self.temp / "market.sqlite")
        connection.execute(
            "UPDATE market_observations SET payload_json = ? WHERE observation_id = ? AND version = ?",
            ('{"bid":"1"}', "tamper", 1),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "MARKET_OBSERVATION_HASH_MISMATCH"):
            self.store.history("tamper")

    def test_conflicting_duplicate_version_fails_without_mutation(self) -> None:
        first = self.quote("conflict", 1)
        self.store.ingest(first, quality_policy=self.quality, rights_policy=self.rights())
        with self.assertRaises(DuplicateConflict):
            self.store.ingest(
                self.quote("conflict", 1, bid="98", ask="99"),
                quality_policy=self.quality,
                rights_policy=self.rights(),
            )
        self.assertEqual(len(self.store.history("conflict")), 1)


if __name__ == "__main__":
    unittest.main()
