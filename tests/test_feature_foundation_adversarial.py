from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.bars import TradeBar
from marketos.canonical import canonical_sha256
from marketos.errors import DomainError, InvariantViolation
from marketos.features import (
    AmbiguousFeaturePoint,
    FeatureDefinition,
    FeaturePoint,
    FeatureStore,
    build_close_return_features,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.sessions import SessionStatus, SessionVersion, VenueCalendar


LISTING_ID = UUID("00000000-0000-0000-0000-000000010100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000010010")
SESSION_ID = UUID("00000000-0000-0000-0000-000000010200")


class FeatureFoundationAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-feature-hardening-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.rights = self.policy()
        self.definition = FeatureDefinition(
            feature_id="close-return",
            version=1,
            family="TECHNICAL",
            lookback=1,
            output_scale=6,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            input_schema_ids=("trade-bar@1",),
            rights_policy_ids=(self.rights.policy_id,),
            null_policy="SKIP",
        )

    @staticmethod
    def policy() -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("non_display", "historical_replay", "derived_data"):
            fields[field] = RightDecision.ALLOW
        return RightsPolicy("feature-rights", fields)

    def session(
        self,
        *,
        version: int = 1,
        close_ns: int = 2_000,
        available_ns: int = 2_100,
        session_date: str = "2026-08-14",
    ) -> SessionVersion:
        return SessionVersion(
            session_id=SESSION_ID,
            version=version,
            venue_id=VENUE_ID,
            session_date=session_date,
            label="REGULAR",
            status=SessionStatus.OPEN,
            open_ns=1_000,
            close_ns=close_ns,
            first_seen_at_ns=available_ns,
            available_to_strategy_at_ns=available_ns,
            revision_time_ns=available_ns,
            source_id="exchange-calendar",
        )

    def bar(self, start_ns: int, end_ns: int, close: str, suffix: str) -> TradeBar:
        price = Price.parse("USD", close, tick_size="0.01")
        return TradeBar(
            listing_id=LISTING_ID,
            venue_id=VENUE_ID,
            interval_start_ns=start_ns,
            interval_end_ns=end_ns,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=Quantity.positive("1"),
            trade_count=1,
            available_to_strategy_at_ns=end_ns + 100,
            input_root_sha256=(suffix * 64)[:64],
            rights_policy_sha256=self.rights.sha256(),
        )

    def build_point(self) -> FeaturePoint:
        calendar = VenueCalendar()
        calendar.append(self.session())
        points = build_close_return_features(
            (
                self.bar(1_000, 1_500, "100", "1"),
                self.bar(1_500, 2_000, "110", "2"),
            ),
            definition=self.definition,
            rights_policy=self.rights,
            calendar=calendar,
            knowledge_time_ns=3_000,
        )
        self.assertEqual(len(points), 1)
        return points[0]

    def test_session_date_must_be_a_real_iso_date(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "INVALID_SESSION_DATE"):
            self.session(session_date="2026-02-30")
        self.assertEqual(date.fromisoformat(self.session().session_date).isoformat(), "2026-08-14")

    def test_feature_point_contains_calendar_lineage_and_consistent_input_root(self) -> None:
        point = self.build_point()
        self.assertEqual(len(point.input_session_sha256), 1)
        self.assertEqual(
            point.input_root_sha256,
            canonical_sha256(
                {
                    "bars": point.input_bar_sha256,
                    "sessions": point.input_session_sha256,
                }
            ),
        )
        self.assertGreaterEqual(point.available_to_strategy_at_ns, 2_100)

    def test_feature_point_rejects_inconsistent_input_root(self) -> None:
        point = self.build_point()
        with self.assertRaisesRegex(InvariantViolation, "FEATURE_INPUT_ROOT_MISMATCH"):
            replace(point, input_root_sha256="f" * 64)

    def test_calendar_revision_changes_feature_lineage(self) -> None:
        bars = (
            self.bar(1_000, 1_500, "100", "1"),
            self.bar(1_500, 2_000, "110", "2"),
        )
        calendar = VenueCalendar()
        v1 = self.session(version=1, close_ns=2_000, available_ns=2_100)
        v2 = self.session(version=2, close_ns=2_100, available_ns=3_100)
        calendar.append(v1)
        calendar.append(v2)
        before = build_close_return_features(
            bars,
            definition=self.definition,
            rights_policy=self.rights,
            calendar=calendar,
            knowledge_time_ns=3_000,
        )[0]
        after = build_close_return_features(
            bars,
            definition=self.definition,
            rights_policy=self.rights,
            calendar=calendar,
            knowledge_time_ns=4_000,
        )[0]
        self.assertEqual(before.input_session_sha256, (v1.sha256(),))
        self.assertEqual(after.input_session_sha256, (v2.sha256(),))
        self.assertNotEqual(before.input_root_sha256, after.input_root_sha256)
        self.assertNotEqual(before.sha256(), after.sha256())

    def test_feature_store_requires_exact_feature_version(self) -> None:
        point = self.build_point()
        with FeatureStore(self.temp / "exact-version.sqlite") as store:
            store.append(point)
            self.assertEqual(
                store.as_of(
                    point.feature_id,
                    point.feature_version,
                    point.listing_id,
                    point.economic_time_ns,
                    knowledge_time_ns=point.available_to_strategy_at_ns,
                ),
                point,
            )
            self.assertIsNone(
                store.as_of(
                    point.feature_id,
                    point.feature_version + 1,
                    point.listing_id,
                    point.economic_time_ns,
                    knowledge_time_ns=point.available_to_strategy_at_ns,
                )
            )

    def test_semantic_feature_collision_is_ambiguous_not_silently_selected(self) -> None:
        first = self.build_point()
        second = replace(first, point_id="independent-point", input_root_sha256=first.input_root_sha256)
        with FeatureStore(self.temp / "ambiguous.sqlite") as store:
            store.append(first)
            store.append(second)
            with self.assertRaisesRegex(AmbiguousFeaturePoint, "AMBIGUOUS_FEATURE_POINT"):
                store.as_of(
                    first.feature_id,
                    first.feature_version,
                    first.listing_id,
                    first.economic_time_ns,
                    knowledge_time_ns=first.available_to_strategy_at_ns,
                )

    def test_duplicate_append_verifies_stored_bytes_before_idempotent_return(self) -> None:
        point = self.build_point()
        path = self.temp / "duplicate-tamper.sqlite"
        with FeatureStore(path) as store:
            store.append(point)
        connection = sqlite3.connect(path)
        connection.execute(
            "UPDATE feature_points SET value_text = ? WHERE point_id = ? AND version = ?",
            ("0.900000", point.point_id, point.version),
        )
        connection.commit()
        connection.close()
        with FeatureStore(path) as store:
            with self.assertRaisesRegex(InvariantViolation, "FEATURE_POINT_HASH_MISMATCH"):
                store.append(point)


if __name__ == "__main__":
    unittest.main()
