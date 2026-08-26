from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.canonical import canonical_json, canonical_sha256
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.events import EventEnvelope, EventKind
from marketos.store import SQLiteEventStore
from marketos.time import EventTime


@dataclass(frozen=True)
class DecimalMarkerDataclass:
    value: dict[str, str]


class DecimalMarkerCanonicalObject:
    def __init__(self, value: dict[str, str]) -> None:
        self.value = value

    def canonical_dict(self) -> dict[str, dict[str, str]]:
        return {"value": self.value}


class DecimalMarkerKey:
    def __str__(self) -> str:
        return "$decimal"


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="marketos-store-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"

    def event(
        self,
        event_id: str,
        value: int = 1,
        sequence: int = 1,
        payload: dict[str, object] | None = None,
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=event_id,
            kind=EventKind.SYSTEM,
            time=EventTime(10, 20, 20, 5),
            source_id="test",
            source_priority=0,
            source_sequence=sequence,
            schema_version="1",
            payload={"value": value} if payload is None else payload,
        )

    def force_update(
        self,
        *,
        trigger: str,
        statement: str,
        parameters: tuple[object, ...],
    ) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(f"DROP TRIGGER {trigger}")
            connection.execute(statement, parameters)
            connection.commit()
        finally:
            connection.close()

    def sql_count(self, table: str) -> int:
        connection = sqlite3.connect(self.path)
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()

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

    def test_reserved_decimal_marker_is_rejected_before_event_insert(self) -> None:
        event = self.event(
            "reserved-event",
            payload={"value": {"$decimal": "1.00"}},
        )
        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(InvariantViolation, "AMBIGUOUS_DECIMAL_MARKER"):
                store.append(event)
            self.assertEqual(store.count(), 0)

    def test_reserved_decimal_marker_is_rejected_before_evidence_insert(self) -> None:
        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(InvariantViolation, "AMBIGUOUS_DECIMAL_MARKER"):
                store.append_evidence("RISK", {"value": {"$decimal": "1.00"}})
            self.assertEqual(store.read_evidence(), ())

    def test_decimal_values_round_trip_without_marker_collision(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(
                self.event(
                    "decimal-event",
                    payload={"value": Decimal("1.00")},
                )
            )
            store.append_evidence("RISK", {"value": Decimal("2.00")})
            event_value = store.read_all()[0].event.payload["value"]
            evidence_value = store.read_evidence()[0].payload["value"]
            self.assertIsInstance(event_value, Decimal)
            self.assertIsInstance(evidence_value, Decimal)
            self.assertEqual(event_value, Decimal("1"))
            self.assertEqual(evidence_value, Decimal("2"))

    def test_historical_reserved_tag_rows_fail_closed_on_open(self) -> None:
        event = self.event(
            "historical-tagged-event",
            payload={"value": {"$datetime": "2026-01-01T00:00:00Z"}},
        )
        event_json = canonical_json(event.canonical_dict())
        event_sha256 = event.sha256()
        chain_sha256 = SQLiteEventStore._chain_hash(1, "0" * 64, event_sha256)
        with SQLiteEventStore(self.path) as store:
            store._connection.execute(
                """
                INSERT INTO events(
                    sequence, event_id, event_sha256, previous_chain_sha256,
                    chain_sha256, event_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, event.event_id, event_sha256, "0" * 64, chain_sha256, event_json),
            )
        with self.assertRaisesRegex(
            InvariantViolation,
            r"EVENT_CHAIN_INTEGRITY_FAILURE.*EVENT_JSON_INVALID:1",
        ):
            SQLiteEventStore(self.path)

    def test_historical_evidence_reserved_tag_rows_fail_closed_on_open(self) -> None:
        payload = {"value": {"$datetime": "2026-01-01T00:00:00Z"}}
        payload_json = canonical_json(payload)
        evidence_sha256 = canonical_sha256({"kind": "RISK", "payload": payload})
        chain_sha256 = SQLiteEventStore._chain_hash(1, "0" * 64, evidence_sha256)
        with SQLiteEventStore(self.path) as store:
            store._connection.execute(
                """
                INSERT INTO evidence(
                    sequence, kind, evidence_sha256, previous_chain_sha256,
                    chain_sha256, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, "RISK", evidence_sha256, "0" * 64, chain_sha256, payload_json),
            )
        with self.assertRaisesRegex(
            InvariantViolation,
            r"EVIDENCE_CHAIN_INTEGRITY_FAILURE.*EVIDENCE_JSON_INVALID:1",
        ):
            SQLiteEventStore(self.path)

    def test_reserved_decimal_marker_is_rejected_inside_canonical_wrappers(self) -> None:
        wrappers = (
            DecimalMarkerDataclass({"$decimal": "3.00"}),
            DecimalMarkerCanonicalObject({"$decimal": "4.00"}),
        )
        with SQLiteEventStore(self.path) as store:
            for index, wrapper in enumerate(wrappers, start=1):
                with self.subTest(wrapper=type(wrapper).__name__):
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_DECIMAL_MARKER",
                    ):
                        store.append(
                            self.event(
                                f"wrapped-event-{index}",
                                payload={"wrapped": wrapper},
                            )
                        )
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_DECIMAL_MARKER",
                    ):
                        store.append_evidence("RISK", {"wrapped": wrapper})
            self.assertEqual(store.count(), 0)

    def test_reserved_decimal_marker_is_rejected_after_key_normalization(self) -> None:
        marker_mapping = {DecimalMarkerKey(): "5.00"}
        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(InvariantViolation, "NON_CANONICAL_PAYLOAD_KEYS"):
                store.append(
                    self.event(
                        "normalized-key-event",
                        payload={"wrapped": marker_mapping},
                    )
                )
            with self.assertRaisesRegex(InvariantViolation, "AMBIGUOUS_DECIMAL_MARKER"):
                store.append_evidence("RISK", {"wrapped": marker_mapping})
            self.assertEqual(store.count(), 0)

    def test_non_reconstructible_payload_types_are_rejected(self) -> None:
        values = (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            UUID("00000000-0000-0000-0000-000000000001"),
            Path("payload.txt"),
            EventKind.SYSTEM,
            DecimalMarkerDataclass({"value": "safe"}),
            DecimalMarkerCanonicalObject({"value": "safe"}),
            frozenset({"safe"}),
        )
        with SQLiteEventStore(self.path) as store:
            for index, value in enumerate(values, start=1):
                with self.subTest(value=type(value).__name__):
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "NON_RECONSTRUCTIBLE_PAYLOAD_TYPE",
                    ):
                        store.append(
                            self.event(
                                f"unsupported-event-{index}",
                                payload={"value": value},
                            )
                        )
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "NON_RECONSTRUCTIBLE_PAYLOAD_TYPE",
                    ):
                        store.append_evidence("RISK", {"value": value})
            self.assertEqual(store.count(), 0)

    def test_event_tuples_round_trip_but_evidence_tuples_are_rejected(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(self.event("tuple-event", payload={"value": (1, 2)}))
            self.assertEqual(store.read_all()[0].event.payload["value"], (1, 2))
            with self.assertRaisesRegex(
                InvariantViolation,
                "NON_RECONSTRUCTIBLE_PAYLOAD_TYPE",
            ):
                store.append_evidence("RISK", {"value": (1, 2)})

    def test_non_decimal_canonical_tags_are_rejected(self) -> None:
        tagged_values = (
            {"$datetime": "2026-01-01T00:00:00Z"},
            {"$path": "payload.txt"},
            {"$uuid": "00000000-0000-0000-0000-000000000001"},
        )
        with SQLiteEventStore(self.path) as store:
            for index, value in enumerate(tagged_values, start=1):
                with self.subTest(index=index):
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_CANONICAL_TAG",
                    ):
                        store.append(
                            self.event(
                                f"tagged-event-{index}",
                                payload={"value": value},
                            )
                        )
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_CANONICAL_TAG",
                    ):
                        store.append_evidence("RISK", {"value": value})

    def test_mapping_key_collisions_are_rejected(self) -> None:
        class CollisionKey:
            def __str__(self) -> str:
                return "same"

        collision = {CollisionKey(): "object-key", "same": "string-key"}
        with self.assertRaisesRegex(InvariantViolation, "NON_CANONICAL_PAYLOAD_KEYS"):
            self.event("collision-event", payload={"value": collision})
        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(InvariantViolation, "NON_CANONICAL_PAYLOAD_KEYS"):
                store.append_evidence("RISK", {"value": collision})
            self.assertEqual(store.count(), 0)

    def test_conflicting_duplicate_is_rejected_without_mutation(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(self.event("same", value=1))
            with self.assertRaisesRegex(DuplicateConflict, "EVENT_ID_CONFLICT"):
                store.append(self.event("same", value=2))
            self.assertEqual(store.count(), 1)
            self.assertTrue(store.verify_chain().ok)

    def test_event_rows_reject_direct_update_and_delete(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(self.event("one"))
        connection = sqlite3.connect(self.path)
        try:
            for statement, parameters in (
                ("UPDATE events SET event_json = ? WHERE event_id = ?", ("{}", "one")),
                ("DELETE FROM events WHERE event_id = ?", ("one",)),
            ):
                with self.subTest(statement=statement):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY_EVENTS"):
                        connection.execute(statement, parameters)
                    connection.rollback()
        finally:
            connection.close()
        self.assertEqual(self.sql_count("events"), 1)

    def test_evidence_rows_reject_direct_update_and_delete(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append_evidence("RISK", {"decision": "NO_TRADE"})
        connection = sqlite3.connect(self.path)
        try:
            for statement in (
                "UPDATE evidence SET payload_json = '{}' WHERE sequence = 1",
                "DELETE FROM evidence WHERE sequence = 1",
            ):
                with self.subTest(statement=statement):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY_EVIDENCE"):
                        connection.execute(statement)
                    connection.rollback()
        finally:
            connection.close()
        self.assertEqual(self.sql_count("evidence"), 1)

    def test_forced_event_tamper_blocks_read_count_append_and_reopen(self) -> None:
        store = SQLiteEventStore(self.path)
        store.append(self.event("one"))
        self.force_update(
            trigger="events_no_update",
            statement="UPDATE events SET event_json = ? WHERE event_id = ?",
            parameters=(json.dumps({"tampered": True}), "one"),
        )
        try:
            for operation in (
                store.read_all,
                store.count,
                lambda: store.append(self.event("one")),
            ):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "EVENT_CHAIN_INTEGRITY_FAILURE",
                    ):
                        operation()
        finally:
            store.close()
        self.assertEqual(self.sql_count("events"), 1)
        with self.assertRaisesRegex(
            InvariantViolation,
            r"(EVENT_CHAIN_INTEGRITY_FAILURE|EVENT_STORE_SCHEMA_INTEGRITY_FAILURE)",
        ):
            SQLiteEventStore(self.path)

    def test_forced_evidence_tamper_blocks_read_append_and_reopen(self) -> None:
        store = SQLiteEventStore(self.path)
        store.append_evidence("RISK", {"decision": "NO_TRADE"})
        self.force_update(
            trigger="evidence_no_update",
            statement="UPDATE evidence SET payload_json = ? WHERE sequence = 1",
            parameters=(json.dumps({"tampered": True}),),
        )
        try:
            for operation in (
                store.read_evidence,
                lambda: store.append_evidence("RISK", {"decision": "ALLOW"}),
            ):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "EVIDENCE_CHAIN_INTEGRITY_FAILURE",
                    ):
                        operation()
        finally:
            store.close()
        self.assertEqual(self.sql_count("evidence"), 1)
        with self.assertRaisesRegex(
            InvariantViolation,
            r"(EVIDENCE_CHAIN_INTEGRITY_FAILURE|EVENT_STORE_SCHEMA_INTEGRITY_FAILURE)",
        ):
            SQLiteEventStore(self.path)

    def test_chain_tamper_is_reported_without_json_decode_escape(self) -> None:
        with SQLiteEventStore(self.path) as store:
            store.append(self.event("one"))
            store.append(self.event("two", sequence=2))
        self.force_update(
            trigger="events_no_update",
            statement="UPDATE events SET event_json = ? WHERE event_id = ?",
            parameters=("{", "one"),
        )
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM events ORDER BY sequence").fetchall()
        finally:
            connection.close()
        verification = SQLiteEventStore.verify_event_rows(rows)
        self.assertFalse(verification.ok)
        self.assertIn("EVENT_JSON_INVALID:1", verification.errors)

    def test_normal_appends_do_not_rescan_full_history(self) -> None:
        class CountingStore(SQLiteEventStore):
            event_verifications = 0
            evidence_verifications = 0

            @classmethod
            def verify_event_rows(cls, rows):
                cls.event_verifications += 1
                return super().verify_event_rows(rows)

            @classmethod
            def verify_evidence_rows(cls, rows):
                cls.evidence_verifications += 1
                return super().verify_evidence_rows(rows)

        with CountingStore(self.path) as store:
            self.assertEqual(CountingStore.event_verifications, 1)
            self.assertEqual(CountingStore.evidence_verifications, 1)
            for index in range(1, 101):
                store.append(self.event(f"event-{index}", sequence=index))
            for index in range(1, 101):
                store.append_evidence("RISK", {"index": index})
            self.assertEqual(CountingStore.event_verifications, 1)
            self.assertEqual(CountingStore.evidence_verifications, 1)

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
