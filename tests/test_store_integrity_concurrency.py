from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from marketos.errors import InvariantViolation
from marketos.events import EventEnvelope, EventKind
from marketos.store import SQLiteEventStore
from marketos.time import EventTime


class StoreIntegrityConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="marketos-store-integrity-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"

    @staticmethod
    def event(index: int) -> EventEnvelope:
        return EventEnvelope(
            event_id=f"event-{index}",
            kind=EventKind.SYSTEM,
            time=EventTime(10, 20, 20, index),
            source_id="test",
            source_priority=0,
            source_sequence=index,
            schema_version="1",
            payload={"index": index},
        )

    def test_evidence_corruption_blocks_every_public_read_surface(self) -> None:
        store = SQLiteEventStore(self.path)
        store.append(self.event(1))
        store.append_evidence("RISK", {"decision": "NO_TRADE"})
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER evidence_no_update")
            connection.execute(
                "UPDATE evidence SET payload_json = ? WHERE sequence = 1",
                (json.dumps({"tampered": True}),),
            )
            connection.commit()
        finally:
            connection.close()
        try:
            for operation in (store.count, store.read_all, store.read_evidence):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "EVIDENCE_CHAIN_INTEGRITY_FAILURE",
                    ):
                        operation()
        finally:
            store.close()

    def test_valid_external_appends_refresh_cached_integrity_state(self) -> None:
        first = SQLiteEventStore(self.path)
        second = SQLiteEventStore(self.path)
        try:
            first.append(self.event(1))
            second.append(self.event(2))
            first.append_evidence("RISK", {"writer": "first"})
            second.append_evidence("RISK", {"writer": "second"})
            self.assertEqual(
                tuple(record.event.event_id for record in first.read_all()),
                ("event-1", "event-2"),
            )
            self.assertEqual(len(second.read_evidence()), 2)
        finally:
            first.close()
            second.close()


if __name__ == "__main__":
    unittest.main()
