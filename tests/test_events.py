from __future__ import annotations

import unittest

from marketos.errors import InvariantViolation
from marketos.events import EventEnvelope, EventKind, sort_events
from marketos.time import ClockQuality, EventTime


class EventTests(unittest.TestCase):
    def event(self, event_id: str, *, sequence: int, kind: EventKind = EventKind.MARKET_SNAPSHOT) -> EventEnvelope:
        return EventEnvelope(
            event_id=event_id,
            kind=kind,
            time=EventTime(
                event_time_ns=100,
                available_at_ns=200,
                received_wall_ns=190,
                received_monotonic_ns=90,
            ),
            source_id="SOURCE-A",
            source_priority=1,
            source_sequence=sequence,
            schema_version="1.0.0",
            payload={"nested": {"value": sequence}},
        )

    def test_total_order_uses_sequence_kind_and_id_tiebreakers(self) -> None:
        events = [
            self.event("z", sequence=2, kind=EventKind.ORDER_INTENT),
            self.event("b", sequence=1, kind=EventKind.ORDER_INTENT),
            self.event("a", sequence=1, kind=EventKind.MARKET_SNAPSHOT),
        ]
        self.assertEqual([event.event_id for event in sort_events(events)], ["a", "b", "z"])

    def test_available_time_before_event_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "LOOKAHEAD_EVENT_TIME"):
            EventTime(
                event_time_ns=200,
                available_at_ns=199,
                received_wall_ns=199,
                received_monotonic_ns=1,
            )

    def test_negative_monotonic_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "NEGATIVE_MONOTONIC_TIME"):
            EventTime(
                event_time_ns=100,
                available_at_ns=100,
                received_wall_ns=100,
                received_monotonic_ns=-1,
            )

    def test_clock_quality_enforces_error_budget_and_freshness(self) -> None:
        quality = ClockQuality(
            source="chrony",
            synchronization_method="NTP",
            last_sync_wall_ns=1_000,
            max_error_ns=50,
            offset_ns=10,
            quality_state="SYNCED",
        )
        self.assertTrue(quality.is_acceptable(now_wall_ns=1_100, max_age_ns=200, max_error_ns=100))
        self.assertFalse(quality.is_acceptable(now_wall_ns=1_500, max_age_ns=200, max_error_ns=100))
        self.assertFalse(quality.is_acceptable(now_wall_ns=1_100, max_age_ns=200, max_error_ns=25))

    def test_payload_is_deeply_immutable(self) -> None:
        event = self.event("immutable", sequence=1)
        with self.assertRaises(TypeError):
            event.payload["x"] = 2  # type: ignore[index]
        nested = event.payload["nested"]
        with self.assertRaises(TypeError):
            nested["value"] = 9  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
