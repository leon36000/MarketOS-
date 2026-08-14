from __future__ import annotations

import unittest
from uuid import UUID

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.sessions import (
    AmbiguousSession,
    SessionStatus,
    SessionVersion,
    VenueCalendar,
)


VENUE_ID = UUID("00000000-0000-0000-0000-000000007010")
SESSION_ID = UUID("00000000-0000-0000-0000-000000007100")
OTHER_SESSION_ID = UUID("00000000-0000-0000-0000-000000007101")


class VenueCalendarTests(unittest.TestCase):
    @staticmethod
    def session(
        version: int,
        *,
        open_ns: int,
        close_ns: int,
        available_ns: int,
        status: SessionStatus = SessionStatus.OPEN,
        session_id: UUID = SESSION_ID,
        label: str = "REGULAR",
    ) -> SessionVersion:
        return SessionVersion(
            session_id=session_id,
            version=version,
            venue_id=VENUE_ID,
            session_date="2026-08-14",
            label=label,
            status=status,
            open_ns=open_ns,
            close_ns=close_ns,
            first_seen_at_ns=available_ns,
            available_to_strategy_at_ns=available_ns,
            revision_time_ns=available_ns,
            source_id="exchange-calendar",
        )

    def test_latest_known_revision_controls_session_boundaries(self) -> None:
        calendar = VenueCalendar()
        regular = self.session(1, open_ns=1_000, close_ns=2_000, available_ns=2_100)
        early_close = self.session(2, open_ns=1_000, close_ns=1_500, available_ns=3_000)
        calendar.append(regular)
        calendar.append(early_close)

        self.assertTrue(calendar.is_open(VENUE_ID, 1_750, knowledge_time_ns=2_500))
        self.assertFalse(calendar.is_open(VENUE_ID, 1_750, knowledge_time_ns=3_500))
        self.assertEqual(
            calendar.session_for_time(VENUE_ID, 1_250, knowledge_time_ns=3_500),
            early_close,
        )
        self.assertFalse(calendar.is_open(VENUE_ID, 1_500, knowledge_time_ns=3_500))
        self.assertEqual(len(calendar.history(SESSION_ID)), 2)

    def test_future_revision_is_invisible_and_cancelled_session_is_closed(self) -> None:
        calendar = VenueCalendar()
        regular = self.session(1, open_ns=1_000, close_ns=2_000, available_ns=2_100)
        cancelled = self.session(
            2,
            open_ns=1_000,
            close_ns=2_000,
            available_ns=4_000,
            status=SessionStatus.CANCELLED,
        )
        calendar.append(regular)
        calendar.append(cancelled)
        self.assertTrue(calendar.is_open(VENUE_ID, 1_500, knowledge_time_ns=3_000))
        self.assertFalse(calendar.is_open(VENUE_ID, 1_500, knowledge_time_ns=4_500))

    def test_overlapping_latest_known_sessions_are_ambiguous(self) -> None:
        calendar = VenueCalendar()
        calendar.append(self.session(1, open_ns=1_000, close_ns=2_000, available_ns=2_100))
        calendar.append(
            self.session(
                1,
                open_ns=1_400,
                close_ns=1_800,
                available_ns=2_100,
                session_id=OTHER_SESSION_ID,
                label="AUCTION",
            )
        )
        with self.assertRaises(AmbiguousSession):
            calendar.session_for_time(VENUE_ID, 1_500, knowledge_time_ns=2_500)

    def test_next_open_is_point_in_time_and_deterministic(self) -> None:
        calendar = VenueCalendar()
        first = self.session(1, open_ns=1_000, close_ns=1_500, available_ns=100)
        second = SessionVersion(
            session_id=OTHER_SESSION_ID,
            version=1,
            venue_id=VENUE_ID,
            session_date="2026-08-15",
            label="REGULAR",
            status=SessionStatus.OPEN,
            open_ns=2_000,
            close_ns=2_500,
            first_seen_at_ns=200,
            available_to_strategy_at_ns=200,
            revision_time_ns=200,
            source_id="exchange-calendar",
        )
        calendar.append(second)
        calendar.append(first)
        self.assertEqual(calendar.next_open(VENUE_ID, 1_600, knowledge_time_ns=300), 2_000)
        self.assertIsNone(calendar.next_open(VENUE_ID, 1_600, knowledge_time_ns=150))

    def test_versions_are_append_only_idempotent_and_identity_stable(self) -> None:
        calendar = VenueCalendar()
        session = self.session(1, open_ns=1_000, close_ns=2_000, available_ns=100)
        self.assertTrue(calendar.append(session))
        self.assertFalse(calendar.append(session))
        conflicting = self.session(1, open_ns=1_000, close_ns=1_900, available_ns=100)
        with self.assertRaises(DuplicateConflict):
            calendar.append(conflicting)
        with self.assertRaisesRegex(InvariantViolation, "SESSION_VERSION_SEQUENCE"):
            calendar.append(self.session(3, open_ns=1_000, close_ns=1_800, available_ns=300))
        with self.assertRaisesRegex(InvariantViolation, "SESSION_IDENTITY_MUTATION"):
            calendar.append(
                SessionVersion(
                    session_id=SESSION_ID,
                    version=2,
                    venue_id=UUID("00000000-0000-0000-0000-000000007011"),
                    session_date="2026-08-14",
                    label="REGULAR",
                    status=SessionStatus.OPEN,
                    open_ns=1_000,
                    close_ns=2_000,
                    first_seen_at_ns=200,
                    available_to_strategy_at_ns=200,
                    revision_time_ns=200,
                    source_id="exchange-calendar",
                )
            )


if __name__ == "__main__":
    unittest.main()
