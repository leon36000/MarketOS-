from __future__ import annotations

import unittest
from uuid import UUID

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.identity import (
    AmbiguousIdentity,
    IdentifierAssignment,
    IdentifierType,
    Instrument,
    ListingStatus,
    ListingVersion,
    SecurityMaster,
    Venue,
)


INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000000002")
VENUE_ID = UUID("00000000-0000-0000-0000-000000000010")
LISTING_OLD = UUID("00000000-0000-0000-0000-000000000100")
LISTING_NEW = UUID("00000000-0000-0000-0000-000000000101")


class SecurityMasterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.master = SecurityMaster()
        self.master.add_instrument(Instrument(INSTRUMENT_ID, "EQUITY", "USD"))
        self.master.add_instrument(Instrument(OTHER_INSTRUMENT_ID, "EQUITY", "USD"))
        self.master.add_venue(Venue(VENUE_ID, "XNAS", "Nasdaq"))

    @staticmethod
    def listing(
        listing_id: UUID,
        instrument_id: UUID,
        *,
        version: int,
        symbol: str,
        valid_from_ns: int,
        valid_to_ns: int | None,
        available_ns: int,
        status: ListingStatus = ListingStatus.ACTIVE,
    ) -> ListingVersion:
        return ListingVersion(
            listing_id=listing_id,
            version=version,
            instrument_id=instrument_id,
            venue_id=VENUE_ID,
            symbol=symbol,
            status=status,
            valid_from_ns=valid_from_ns,
            valid_to_ns=valid_to_ns,
            first_seen_at_ns=available_ns,
            available_to_strategy_at_ns=available_ns,
            revision_time_ns=available_ns,
        )

    def test_symbol_is_not_identity_and_can_be_reused_across_time(self) -> None:
        self.master.append_listing(
            self.listing(
                LISTING_OLD,
                INSTRUMENT_ID,
                version=1,
                symbol="ABC",
                valid_from_ns=0,
                valid_to_ns=100,
                available_ns=10,
                status=ListingStatus.DELISTED,
            )
        )
        self.master.append_listing(
            self.listing(
                LISTING_NEW,
                OTHER_INSTRUMENT_ID,
                version=1,
                symbol="ABC",
                valid_from_ns=100,
                valid_to_ns=None,
                available_ns=120,
            )
        )

        old = self.master.resolve_symbol("ABC", "XNAS", economic_time_ns=50, knowledge_time_ns=130)
        self.assertEqual(old.listing_id, LISTING_OLD)
        self.assertEqual(old.instrument_id, INSTRUMENT_ID)
        self.assertIsNone(
            self.master.resolve_symbol("ABC", "XNAS", economic_time_ns=150, knowledge_time_ns=110)
        )
        new = self.master.resolve_symbol("ABC", "XNAS", economic_time_ns=150, knowledge_time_ns=130)
        self.assertEqual(new.listing_id, LISTING_NEW)
        self.assertEqual(new.instrument_id, OTHER_INSTRUMENT_ID)
        self.assertEqual(len(self.master.listing_history(LISTING_OLD)), 1)

    def test_cross_listings_remain_distinct(self) -> None:
        other_venue = Venue(UUID("00000000-0000-0000-0000-000000000011"), "XTSE", "Toronto")
        self.master.add_venue(other_venue)
        nasdaq = self.listing(
            LISTING_OLD,
            INSTRUMENT_ID,
            version=1,
            symbol="ABC",
            valid_from_ns=0,
            valid_to_ns=None,
            available_ns=10,
        )
        toronto = ListingVersion(
            listing_id=LISTING_NEW,
            version=1,
            instrument_id=INSTRUMENT_ID,
            venue_id=other_venue.venue_id,
            symbol="ABC",
            status=ListingStatus.ACTIVE,
            valid_from_ns=0,
            valid_to_ns=None,
            first_seen_at_ns=10,
            available_to_strategy_at_ns=10,
            revision_time_ns=10,
        )
        self.master.append_listing(nasdaq)
        self.master.append_listing(toronto)
        self.assertNotEqual(
            self.master.resolve_symbol("ABC", "XNAS", economic_time_ns=50, knowledge_time_ns=50).listing_id,
            self.master.resolve_symbol("ABC", "XTSE", economic_time_ns=50, knowledge_time_ns=50).listing_id,
        )

    def test_overlapping_visible_listings_are_quarantined_as_ambiguous(self) -> None:
        self.master.append_listing(
            self.listing(
                LISTING_OLD,
                INSTRUMENT_ID,
                version=1,
                symbol="ABC",
                valid_from_ns=0,
                valid_to_ns=None,
                available_ns=10,
            )
        )
        self.master.append_listing(
            self.listing(
                LISTING_NEW,
                OTHER_INSTRUMENT_ID,
                version=1,
                symbol="ABC",
                valid_from_ns=0,
                valid_to_ns=None,
                available_ns=10,
            )
        )
        with self.assertRaises(AmbiguousIdentity):
            self.master.resolve_symbol("ABC", "XNAS", economic_time_ns=50, knowledge_time_ns=50)

    def test_listing_versions_are_append_only_and_idempotent(self) -> None:
        listing = self.listing(
            LISTING_OLD,
            INSTRUMENT_ID,
            version=1,
            symbol="ABC",
            valid_from_ns=0,
            valid_to_ns=None,
            available_ns=10,
        )
        self.assertTrue(self.master.append_listing(listing))
        self.assertFalse(self.master.append_listing(listing))
        conflicting = self.listing(
            LISTING_OLD,
            INSTRUMENT_ID,
            version=1,
            symbol="XYZ",
            valid_from_ns=0,
            valid_to_ns=None,
            available_ns=10,
        )
        with self.assertRaises(DuplicateConflict):
            self.master.append_listing(conflicting)
        with self.assertRaisesRegex(InvariantViolation, "LISTING_VERSION_SEQUENCE"):
            self.master.append_listing(
                self.listing(
                    LISTING_OLD,
                    INSTRUMENT_ID,
                    version=3,
                    symbol="ABC",
                    valid_from_ns=0,
                    valid_to_ns=None,
                    available_ns=30,
                )
            )

    def test_identifier_assignments_are_bitemporal(self) -> None:
        assignment = IdentifierAssignment(
            assignment_id=UUID("00000000-0000-0000-0000-000000000200"),
            version=1,
            entity_id=INSTRUMENT_ID,
            identifier_type=IdentifierType.FIGI,
            value="BBG000TEST01",
            valid_from_ns=0,
            valid_to_ns=None,
            first_seen_at_ns=20,
            available_to_strategy_at_ns=20,
            revision_time_ns=20,
        )
        self.master.append_identifier(assignment)
        self.assertIsNone(
            self.master.resolve_identifier(
                IdentifierType.FIGI,
                "BBG000TEST01",
                economic_time_ns=10,
                knowledge_time_ns=19,
            )
        )
        visible = self.master.resolve_identifier(
            IdentifierType.FIGI,
            "BBG000TEST01",
            economic_time_ns=10,
            knowledge_time_ns=20,
        )
        self.assertEqual(visible.entity_id, INSTRUMENT_ID)


if __name__ == "__main__":
    unittest.main()
