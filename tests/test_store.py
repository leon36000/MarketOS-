from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from marketos.errors import DuplicateConflict
from marketos.events import EventEnvelope, EventKind
from marketos.store import SQLiteEventStore
from marketos.time import EventTime


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="marketos-store-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"

    def event(self, event_id: str, value: int = 1, sequence: int = 1) -> EventEnvelope:
        return EventEnvelope(
            event_id=event_id,
            kind=EventKind.SYSTEM,
            time=EventTime(10, 20, 20, 5),
            source_id="test",
            source_priority=0,
            source_sequence=sequence,
            schema_version="1",
            payload={"value": value},
        )

    def test_append_is_durable_and_reopenable(self) -> None:
        with SQLiteEventStore(self.path) as store:
            result = store.append(self.event("one"))
            self.assertTrue(result.inserted)
            self.assertEqual(result.sequence, 1)
        with SQLiteEventStore(self.path) as reopened:
            self.assertEqual([record.event.event_id for record in reopened.read_all()], ["one"])
            self.assertTrue(reopened.verify_chain().ok)

    def test_identical_duplicate_is_idempotent(self) -> None:
        with SQLiteEventStore(self.path) as store:
            first = store.append(self.event("same"))
            second = store.append(self.event("same"))
            self.assertTrue(first.inserted)
            self.assertFalse(second.inserted)
            self.assertEqual(second.sequence, first.sequence)
            self.assertEqual(store.count(), 1)

    def test_conflicting_duplicate_is_rejected_without_mutation(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(self.event("same", value=1))
            with self.assertRaisesRegex(DuplicateConflict, "EVENT_ID_CONFLICT"):
                store.append(self.event("same", value=2))
            self.assertEqual(store.count(), 1)
            self.assertTrue(store.verify_chain().ok)

    def test_chain_tamper_is_detected(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(self.event("one"))
            store.append(self.event("two", sequence=2))
        connection = sqlite3.connect(self.path)
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = ?",
            (json.dumps({"tampered": True}), "one"),
        )
        connection.commit()
        connection.close()
        with SQLiteEventStore(self.path) as store:
            verification = store.verify_chain()
            self.assertFalse(verification.ok)
            self.assertIn("EVENT_HASH_MISMATCH:1", verification.errors)

    def test_append_many_is_atomic_on_conflict(self) -> None:
        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(DuplicateConflict, "EVENT_ID_CONFLICT"):
                store.append_many([self.event("dup", value=1), self.event("dup", value=2)])
            self.assertEqual(store.count(), 0)

    def test_evidence_is_hash_chained_and_durable(self) -> None:
        with SQLiteEventStore(self.path) as store:
            first = store.append_evidence("RISK", {"decision": "NO_TRADE"})
            second = store.append_evidence("RISK", {"decision": "ALLOW"})
            self.assertEqual(first.sequence, 1)
            self.assertEqual(second.previous_chain_sha256, first.chain_sha256)
            self.assertTrue(store.verify_evidence_chain().ok)
        with SQLiteEventStore(self.path) as store:
            self.assertEqual(len(store.read_evidence()), 2)


if __name__ == "__main__":
    unittest.main()
