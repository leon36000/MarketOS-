from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.corporate_actions import AdjustmentFactor, AdjustmentSeries
from marketos.datafabric import (
    DatasetPublisher,
    DatasetSpec,
    TemporalFact,
    TemporalFactStore,
)
from marketos.errors import InvariantViolation
from marketos.identity import (
    IdentifierAssignment,
    IdentifierType,
    Instrument,
    ListingStatus,
    ListingVersion,
    SecurityMaster,
    Venue,
)
from marketos.money import Price
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy


INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000003001")
VENUE_ID = UUID("00000000-0000-0000-0000-000000003010")
LISTING_ID = UUID("00000000-0000-0000-0000-000000003100")


class TemporalSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-temporal-semantics-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    @staticmethod
    def rights() -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("storage", "historical_replay", "derived_data"):
            fields[field] = RightDecision.ALLOW
        return RightsPolicy("rights-1", fields)

    @staticmethod
    def spec(*, source_versions=("source@1",), rights_policy_ids=("rights-1",)) -> DatasetSpec:
        return DatasetSpec(
            "security-master",
            "v1",
            "security-master@1",
            source_versions,
            100,
            110,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            rights_policy_ids,
            "quality-1",
            "lineage-1",
        )

    def master(self) -> SecurityMaster:
        master = SecurityMaster()
        master.add_instrument(Instrument(INSTRUMENT_ID, "EQUITY", "USD"))
        master.add_venue(Venue(VENUE_ID, "XNAS", "Nasdaq"))
        return master

    def test_latest_known_listing_revision_controls_economic_validity(self) -> None:
        master = self.master()
        master.append_listing(
            ListingVersion(
                LISTING_ID, 1, INSTRUMENT_ID, VENUE_ID, "ABC", ListingStatus.ACTIVE,
                0, None, 10, 10, 10,
            )
        )
        master.append_listing(
            ListingVersion(
                LISTING_ID, 2, INSTRUMENT_ID, VENUE_ID, "ABC", ListingStatus.ACTIVE,
                100, None, 20, 20, 20,
            )
        )
        self.assertIsNotNone(
            master.resolve_symbol("ABC", "XNAS", economic_time_ns=50, knowledge_time_ns=15)
        )
        self.assertIsNone(
            master.resolve_symbol("ABC", "XNAS", economic_time_ns=50, knowledge_time_ns=30)
        )

    def test_latest_known_identifier_revision_controls_economic_validity(self) -> None:
        master = self.master()
        assignment_id = UUID("00000000-0000-0000-0000-000000003200")
        master.append_identifier(
            IdentifierAssignment(
                assignment_id, 1, INSTRUMENT_ID, IdentifierType.FIGI, "BBG000TEST01",
                0, None, 10, 10, 10,
            )
        )
        master.append_identifier(
            IdentifierAssignment(
                assignment_id, 2, INSTRUMENT_ID, IdentifierType.FIGI, "BBG000TEST01",
                100, None, 20, 20, 20,
            )
        )
        self.assertIsNotNone(
            master.resolve_identifier(
                IdentifierType.FIGI,
                "BBG000TEST01",
                economic_time_ns=50,
                knowledge_time_ns=15,
            )
        )
        self.assertIsNone(
            master.resolve_identifier(
                IdentifierType.FIGI,
                "BBG000TEST01",
                economic_time_ns=50,
                knowledge_time_ns=30,
            )
        )

    def test_latest_known_fact_revision_does_not_resurrect_old_interval(self) -> None:
        with TemporalFactStore(self.temp / "facts.sqlite") as store:
            store.append(TemporalFact("fact-1", "issuer:1:status", 1, 0, None, 10, 10, "source", {"status": "ACTIVE"}))
            store.append(TemporalFact("fact-1", "issuer:1:status", 2, 100, None, 20, 20, "source", {"status": "ACTIVE"}))
            self.assertIsNotNone(
                store.as_of("issuer:1:status", economic_time_ns=50, knowledge_time_ns=15)
            )
            self.assertIsNone(
                store.as_of("issuer:1:status", economic_time_ns=50, knowledge_time_ns=30)
            )

    def test_latest_known_adjustment_revision_controls_applicability(self) -> None:
        series = AdjustmentSeries()
        factor_id = UUID("00000000-0000-0000-0000-000000003300")
        series.append(AdjustmentFactor(factor_id, 1, INSTRUMENT_ID, 200, Decimal("0.5"), 10, "a" * 64))
        series.append(AdjustmentFactor(factor_id, 2, INSTRUMENT_ID, 50, Decimal("0.25"), 20, "a" * 64))
        raw = Price.parse("USD", "100", tick_size="0.01")
        self.assertIsNotNone(
            series.adjust(raw, INSTRUMENT_ID, raw_time_ns=100, knowledge_time_ns=15)
        )
        self.assertIsNone(
            series.adjust(raw, INSTRUMENT_ID, raw_time_ns=100, knowledge_time_ns=30)
        )

    def test_temporal_fact_hash_is_verified_on_read(self) -> None:
        path = self.temp / "facts.sqlite"
        with TemporalFactStore(path) as store:
            store.append(TemporalFact("fact-1", "key", 1, 0, None, 10, 10, "source", {"value": 1}))
        connection = sqlite3.connect(path)
        connection.execute(
            "UPDATE temporal_facts SET payload_json = ? WHERE fact_id = ? AND version = ?",
            ('{"value":2}', "fact-1", 1),
        )
        connection.commit()
        connection.close()
        with TemporalFactStore(path) as store:
            with self.assertRaisesRegex(InvariantViolation, "TEMPORAL_FACT_HASH_MISMATCH"):
                store.history("fact-1")

    def test_existing_dataset_bytes_are_verified_before_idempotent_return(self) -> None:
        publisher = DatasetPublisher(self.temp / "lake")
        spec = self.spec()
        result = publisher.publish(
            spec,
            {"part-000.jsonl": b'{"id":1}\n'},
            rights_policies=(self.rights(),),
            quality_pass=True,
            lineage_complete=True,
        )
        (result.commit_path.parent / "part-000.jsonl").write_bytes(b"tampered")
        with self.assertRaisesRegex(InvariantViolation, "DATASET_FILE_HASH_MISMATCH"):
            publisher.publish(
                spec,
                {"part-000.jsonl": b'{"id":1}\n'},
                rights_policies=(self.rights(),),
                quality_pass=True,
                lineage_complete=True,
            )

    def test_duplicate_source_or_rights_ids_are_rejected_not_normalized(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "DUPLICATE_SOURCE_VERSION"):
            self.spec(source_versions=("source@1", "source@1"))
        with self.assertRaisesRegex(InvariantViolation, "DUPLICATE_RIGHTS_POLICY_ID"):
            self.spec(rights_policy_ids=("rights-1", "rights-1"))


if __name__ == "__main__":
    unittest.main()
