from __future__ import annotations

from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
