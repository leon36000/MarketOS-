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

    def test_existing_legacy_schema_receives_append_only_guards(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(
                """
                CREATE TABLE events (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_sha256 TEXT NOT NULL,
                    previous_chain_sha256 TEXT NOT NULL,
                    chain_sha256 TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL
                );
                CREATE TABLE evidence (
                    sequence INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    previous_chain_sha256 TEXT NOT NULL,
                    chain_sha256 TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                """
            )
            connection.commit()
        finally:
            connection.close()
        with SQLiteEventStore(self.path) as store:
            store.append(self.event(1))
            store.append_evidence("RISK", {"decision": "NO_TRADE"})
        connection = sqlite3.connect(self.path)
        try:
            triggers = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
        finally:
            connection.close()
        self.assertEqual(
            triggers,
            {
                "events_no_update",
                "events_no_delete",
                "evidence_no_update",
                "evidence_no_delete",
            },
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

    def test_malformed_evidence_json_is_reported_not_raised(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append_evidence("RISK", {"decision": "NO_TRADE"})
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("DROP TRIGGER evidence_no_update")
            connection.execute(
                "UPDATE evidence SET payload_json = ? WHERE sequence = 1",
                ("{",),
            )
            connection.commit()
            rows = connection.execute(
                "SELECT * FROM evidence ORDER BY sequence"
            ).fetchall()
        finally:
            connection.close()
        verification = SQLiteEventStore.verify_evidence_rows(rows)
        self.assertFalse(verification.ok)
        self.assertIn("EVIDENCE_JSON_INVALID:1", verification.errors)

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
