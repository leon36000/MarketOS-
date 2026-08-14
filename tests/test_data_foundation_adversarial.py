from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import UUID

from marketos.corporate_actions import (
    ActionFamily,
    ActionStatus,
    CorporateActionBook,
    CorporateActionVersion,
)
from marketos.datafabric import (
    DatasetPublisher,
    DatasetSpec,
    PublicationDenied,
    TemporalFact,
    TemporalFactStore,
)
from marketos.errors import DomainError, InvariantViolation
from marketos.identity import (
    IdentifierAssignment,
    IdentifierType,
    Instrument,
    ListingStatus,
    ListingVersion,
    SecurityMaster,
    Venue,
)
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy


INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000001001")
VENUE_ID = UUID("00000000-0000-0000-0000-000000001010")
LISTING_ID = UUID("00000000-0000-0000-0000-000000001100")


class DataFoundationAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-data-hardening-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    @staticmethod
    def rights() -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("storage", "historical_replay", "derived_data"):
            fields[field] = RightDecision.ALLOW
        return RightsPolicy("rights-1", fields)

    @staticmethod
    def dataset_spec() -> DatasetSpec:
        return DatasetSpec(
            dataset_id="security-master",
            version="v1",
            schema_id="security-master@1",
            source_versions=("source@1",),
            economic_cutoff_ns=100,
            knowledge_cutoff_ns=110,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            dependency_lock_sha256="c" * 64,
            rights_policy_ids=("rights-1",),
            quality_report_id="quality-1",
            lineage_run_id="run-1",
        )

    def test_listing_can_receive_versioned_local_and_vendor_identifiers(self) -> None:
        master = SecurityMaster()
        master.add_instrument(Instrument(INSTRUMENT_ID, "EQUITY", "USD"))
        master.add_venue(Venue(VENUE_ID, "XNAS", "Nasdaq"))
        master.append_listing(
            ListingVersion(
                listing_id=LISTING_ID,
                version=1,
                instrument_id=INSTRUMENT_ID,
                venue_id=VENUE_ID,
                symbol="ABC",
                status=ListingStatus.ACTIVE,
                valid_from_ns=0,
                valid_to_ns=None,
                first_seen_at_ns=10,
                available_to_strategy_at_ns=10,
                revision_time_ns=10,
            )
        )
        assignment = IdentifierAssignment(
            assignment_id=UUID("00000000-0000-0000-0000-000000001200"),
            version=1,
            entity_id=LISTING_ID,
            identifier_type=IdentifierType.VENDOR_SYMBOL,
            value="ABC.OQ",
            valid_from_ns=0,
            valid_to_ns=None,
            first_seen_at_ns=20,
            available_to_strategy_at_ns=20,
            revision_time_ns=20,
        )
        self.assertTrue(master.append_identifier(assignment))
        resolved = master.resolve_identifier(
            IdentifierType.VENDOR_SYMBOL,
            "ABC.OQ",
            economic_time_ns=50,
            knowledge_time_ns=50,
        )
        self.assertEqual(resolved.entity_id, LISTING_ID)

    def test_quarantined_corporate_action_is_not_effective(self) -> None:
        book = CorporateActionBook()
        book.append(
            CorporateActionVersion(
                action_id=UUID("00000000-0000-0000-0000-000000001300"),
                version=1,
                instrument_id=INSTRUMENT_ID,
                family=ActionFamily.SPLIT,
                status=ActionStatus.QUARANTINED,
                announcement_ns=10,
                ex_date_ns=100,
                record_date_ns=110,
                effective_date_ns=100,
                payable_date_ns=None,
                expiration_date_ns=None,
                first_seen_at_ns=20,
                available_to_strategy_at_ns=20,
                revision_time_ns=20,
                source_id="conflicting-sources",
                terms={"new_shares": "2", "old_shares": "1"},
            )
        )
        self.assertEqual(
            book.effective_between(0, 200, knowledge_time_ns=50),
            (),
        )

    def test_temporal_fact_conflict_is_quarantined_not_silently_selected(self) -> None:
        store = TemporalFactStore(self.temp / "facts.sqlite")
        self.addCleanup(store.close)
        store.append(
            TemporalFact("fact-a", "issuer:1:status", 1, 0, None, 10, 10, "source-a", {"status": "ACTIVE"})
        )
        store.append(
            TemporalFact("fact-b", "issuer:1:status", 1, 0, None, 10, 10, "source-b", {"status": "DELISTED"})
        )
        with self.assertRaisesRegex(DomainError, "AMBIGUOUS_TEMPORAL_FACT"):
            store.as_of("issuer:1:status", economic_time_ns=5, knowledge_time_ns=20)

    def test_duplicate_rights_policy_ids_block_dataset_publication(self) -> None:
        publisher = DatasetPublisher(self.temp / "lake")
        policy = self.rights()
        with self.assertRaisesRegex(PublicationDenied, "DUPLICATE_RIGHTS_POLICY_ID"):
            publisher.publish(
                self.dataset_spec(),
                {"part-000.jsonl": b'{"id":1}\n'},
                rights_policies=(policy, policy),
                quality_pass=True,
                lineage_complete=True,
            )
        self.assertEqual(publisher.list_versions("security-master"), ())

    def test_noncanonical_dataset_path_is_rejected_before_staging(self) -> None:
        publisher = DatasetPublisher(self.temp / "lake")
        with self.assertRaisesRegex(InvariantViolation, "NON_CANONICAL_DATASET_PATH"):
            publisher.publish(
                self.dataset_spec(),
                {"nested//part-000.jsonl": b'{"id":1}\n'},
                rights_policies=(self.rights(),),
                quality_pass=True,
                lineage_complete=True,
            )
        self.assertEqual(publisher.list_versions("security-master"), ())


if __name__ == "__main__":
    unittest.main()
