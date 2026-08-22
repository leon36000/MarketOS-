from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from marketos.errors import InvariantViolation
from marketos.events import EventEnvelope, EventKind
from marketos.store import SQLiteEventStore
from marketos.time import EventTime


class StoreSchemaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="marketos-store-schema-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"

    @staticmethod
    def event() -> EventEnvelope:
        return EventEnvelope(
            event_id="event-1",
            kind=EventKind.SYSTEM,
            time=EventTime(10, 20, 20, 1),
            source_id="test",
            source_priority=0,
            source_sequence=1,
            schema_version="1",
            payload={"index": 1},
        )

    def test_unexpected_temporary_ledger_trigger_blocks_write(self) -> None:
        store = SQLiteEventStore(self.path)
        try:
            store._connection.executescript(
                """
                CREATE TEMP TRIGGER events_temp_after_insert
                AFTER INSERT ON events
                BEGIN
                    SELECT 1;
                END;
                """
            )
            event = self.event()
            with self.assertRaisesRegex(
                InvariantViolation,
                "EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:events_temp_after_insert",
            ):
                store.append(event)
        finally:
            store.close()

    def test_invalid_existing_schema_is_not_repaired_before_rejection(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "CREATE TABLE events (sequence INTEGER PRIMARY KEY, event_id TEXT)"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(
            InvariantViolation,
            "EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:events",
        ):
            SQLiteEventStore(self.path)

        connection = sqlite3.connect(self.path)
        try:
            objects = tuple(
                connection.execute(
                    """
                    SELECT type, name
                    FROM sqlite_master
                    WHERE name IN (
                        'events', 'evidence', 'events_no_update',
                        'events_no_delete', 'evidence_no_update',
                        'evidence_no_delete'
                    )
                    ORDER BY type, name
                    """
                ).fetchall()
            )
        finally:
            connection.close()
        self.assertEqual(objects, (("table", "events"),))

    def test_invalid_existing_schema_is_not_switched_to_wal_before_rejection(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "CREATE TABLE events (sequence INTEGER PRIMARY KEY, event_id TEXT)"
            )
            connection.commit()
        finally:
            connection.close()
        database_before = self.path.read_bytes()

        with self.assertRaisesRegex(
            InvariantViolation,
            "EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:events",
        ):
            SQLiteEventStore(self.path)

        self.assertEqual(self.path.read_bytes(), database_before)
        connection = sqlite3.connect(self.path)
        try:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        finally:
            connection.close()
        self.assertEqual(journal_mode.lower(), "delete")


if __name__ == "__main__":
    unittest.main()
