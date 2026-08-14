from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.bars import BarDerivationDenied, build_trade_bars
from marketos.datafabric import RawEvidenceStore
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.marketdata import (
    MarketDataStore,
    MarketObservation,
    ObservationKind,
    ObservationStatus,
    QualityPolicy,
    QuotePayload,
    TradePayload,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.time import EventTime


LISTING_ID = UUID("00000000-0000-0000-0000-000000006100")
OTHER_LISTING_ID = UUID("00000000-0000-0000-0000-000000006101")
VENUE_ID = UUID("00000000-0000-0000-0000-000000006010")


class MarketDataAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-market-authority-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.raw = RawEvidenceStore(self.temp / "raw")
        self.addCleanup(self.raw.close)
        self.store = MarketDataStore(self.temp / "market.sqlite", raw_evidence_store=self.raw)
        self.addCleanup(self.store.close)

    @staticmethod
    def rights(*, derived: bool = True, audit_reporting: bool = False) -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("storage", "non_display", "historical_replay"):
            fields[field] = RightDecision.ALLOW
        if derived:
            fields["derived_data"] = RightDecision.ALLOW
        if audit_reporting:
            fields["audit_reporting"] = RightDecision.ALLOW
        return RightsPolicy("market-rights", fields)

    @staticmethod
    def quality(*, max_latency_ns: int = 100) -> QualityPolicy:
        return QualityPolicy(
            max_future_skew_ns=5,
            max_latency_ns=max_latency_ns,
            crossed_quote_action="QUARANTINE",
            zero_trade_price_action="QUARANTINE",
        )

    def quote(self, observation_id: str = "quote") -> MarketObservation:
        raw_ref = self.raw.put(
            f"raw:{observation_id}".encode(),
            source_id="fixture-feed",
            retrieved_at_ns=90,
            media_type="application/octet-stream",
            rights_policy_ids=("market-rights",),
        )
        return MarketObservation(
            observation_id=observation_id,
            version=1,
            kind=ObservationKind.QUOTE,
            status=ObservationStatus.ORIGINAL,
            listing_id=LISTING_ID,
            venue_id=VENUE_ID,
            source_id="fixture-feed",
            channel_id="quotes",
            source_sequence=1,
            time=EventTime(100, 110, 110, 110),
            raw_content_sha256=raw_ref.content_sha256,
            schema_version="quote@1",
            payload=QuotePayload(
                bid=Price.parse("USD", "99", tick_size="0.01"),
                ask=Price.parse("USD", "100", tick_size="0.01"),
                bid_size=Quantity.parse("10"),
                ask_size=Quantity.parse("10"),
            ),
        )

    @staticmethod
    def trade(
        observation_id: str,
        version: int,
        listing_id: UUID,
        *,
        status: ObservationStatus = ObservationStatus.ORIGINAL,
    ) -> MarketObservation:
        return MarketObservation(
            observation_id=observation_id,
            version=version,
            kind=ObservationKind.TRADE,
            status=status,
            listing_id=listing_id,
            venue_id=VENUE_ID,
            source_id="fixture-feed",
            channel_id="trades",
            source_sequence=version,
            time=EventTime(10, 20 + version, 20 + version, 20 + version),
            raw_content_sha256=(f"{version:x}" * 64)[:64].ljust(64, "0"),
            schema_version="trade@1",
            payload=TradePayload(
                price=Price.parse("USD", "100", tick_size="0.01"),
                size=Quantity.positive("1"),
                condition_codes=(),
            ),
        )

    def test_ingestion_result_records_policy_hashes(self) -> None:
        quality = self.quality()
        rights = self.rights()
        result = self.store.ingest(
            self.quote(),
            quality_policy=quality,
            rights_policy=rights,
        )
        self.assertEqual(result.quality_policy_sha256, quality.sha256())
        self.assertEqual(result.rights_policy_sha256, rights.sha256())

    def test_duplicate_under_different_quality_policy_is_a_conflict(self) -> None:
        observation = self.quote()
        self.store.ingest(
            observation,
            quality_policy=self.quality(max_latency_ns=100),
            rights_policy=self.rights(),
        )
        with self.assertRaisesRegex(DuplicateConflict, "INGESTION_POLICY_CONFLICT"):
            self.store.ingest(
                observation,
                quality_policy=self.quality(max_latency_ns=200),
                rights_policy=self.rights(),
            )

    def test_duplicate_under_different_rights_policy_is_a_conflict(self) -> None:
        observation = self.quote()
        self.store.ingest(
            observation,
            quality_policy=self.quality(),
            rights_policy=self.rights(audit_reporting=False),
        )
        with self.assertRaisesRegex(DuplicateConflict, "INGESTION_POLICY_CONFLICT"):
            self.store.ingest(
                observation,
                quality_policy=self.quality(),
                rights_policy=self.rights(audit_reporting=True),
            )

    def test_raw_evidence_tamper_blocks_canonical_reads(self) -> None:
        observation = self.quote()
        self.store.ingest(
            observation,
            quality_policy=self.quality(),
            rights_policy=self.rights(),
        )
        self.raw._path(observation.raw_content_sha256).write_bytes(b"tampered")
        with self.assertRaisesRegex(InvariantViolation, "MARKET_RAW_EVIDENCE_MISMATCH"):
            self.store.history(observation.observation_id)

    def test_quality_decision_tamper_is_detected(self) -> None:
        observation = self.quote()
        self.store.ingest(
            observation,
            quality_policy=self.quality(),
            rights_policy=self.rights(),
        )
        connection = sqlite3.connect(self.temp / "market.sqlite")
        connection.execute(
            "UPDATE market_observations SET reasons_json = ? WHERE observation_id = ? AND version = ?",
            ('["INJECTED"]', observation.observation_id, observation.version),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "MARKET_QUALITY_DECISION_HASH_MISMATCH"):
            self.store.history(observation.observation_id)

    def test_bar_derivation_requires_explicit_rights(self) -> None:
        trade = self.trade("trade", 1, LISTING_ID)
        with self.assertRaisesRegex(BarDerivationDenied, "BAR_DERIVATION_RIGHT_DENIED"):
            build_trade_bars(
                (trade,),
                interval_ns=100,
                knowledge_time_ns=100,
                rights_policy=self.rights(derived=False),
            )
        bars = build_trade_bars(
            (trade,),
            interval_ns=100,
            knowledge_time_ns=100,
            rights_policy=self.rights(derived=True),
        )
        self.assertEqual(len(bars), 1)

    def test_bar_revision_identity_mutation_is_rejected(self) -> None:
        original = self.trade("trade", 1, LISTING_ID)
        correction = self.trade(
            "trade",
            2,
            OTHER_LISTING_ID,
            status=ObservationStatus.CORRECTED,
        )
        with self.assertRaisesRegex(InvariantViolation, "BAR_OBSERVATION_IDENTITY_MUTATION"):
            build_trade_bars(
                (original, correction),
                interval_ns=100,
                knowledge_time_ns=100,
                rights_policy=self.rights(),
            )


if __name__ == "__main__":
    unittest.main()
