from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.bars import TradeBar
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.features import (
    FeatureDefinition,
    FeatureDerivationDenied,
    FeaturePoint,
    FeatureStore,
    build_close_return_features,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.sessions import SessionStatus, SessionVersion, VenueCalendar


LISTING_ID = UUID("00000000-0000-0000-0000-000000008100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000008010")
SESSION_ID = UUID("00000000-0000-0000-0000-000000008200")


class FeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-features-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.rights = self.policy(derived=True)
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
    def policy(*, derived: bool) -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("non_display", "historical_replay"):
            fields[field] = RightDecision.ALLOW
        if derived:
            fields["derived_data"] = RightDecision.ALLOW
        return RightsPolicy("feature-rights", fields)

    def bar(
        self,
        start_ns: int,
        end_ns: int,
        close: str,
        *,
        available_ns: int | None = None,
        input_suffix: str = "1",
    ) -> TradeBar:
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
            available_to_strategy_at_ns=end_ns if available_ns is None else available_ns,
            input_root_sha256=(input_suffix * 64)[:64],
            rights_policy_sha256=self.rights.sha256(),
        )

    @staticmethod
    def calendar(*, early_close_available_ns: int | None = None) -> VenueCalendar:
        calendar = VenueCalendar()
        calendar.append(
            SessionVersion(
                session_id=SESSION_ID,
                version=1,
                venue_id=VENUE_ID,
                session_date="2026-08-14",
                label="REGULAR",
                status=SessionStatus.OPEN,
                open_ns=1_000,
                close_ns=2_000,
                first_seen_at_ns=2_100,
                available_to_strategy_at_ns=2_100,
                revision_time_ns=2_100,
                source_id="exchange-calendar",
            )
        )
        if early_close_available_ns is not None:
            calendar.append(
                SessionVersion(
                    session_id=SESSION_ID,
                    version=2,
                    venue_id=VENUE_ID,
                    session_date="2026-08-14",
                    label="REGULAR",
                    status=SessionStatus.OPEN,
                    open_ns=1_000,
                    close_ns=1_500,
                    first_seen_at_ns=early_close_available_ns,
                    available_to_strategy_at_ns=early_close_available_ns,
                    revision_time_ns=early_close_available_ns,
                    source_id="exchange-calendar",
                )
            )
        return calendar

    def test_close_returns_are_exact_deterministic_and_point_in_time(self) -> None:
        bars = (
            self.bar(1_000, 1_500, "100", available_ns=2_200, input_suffix="1"),
            self.bar(1_500, 2_000, "110", available_ns=2_300, input_suffix="2"),
        )
        first = build_close_return_features(
            tuple(reversed(bars)),
            definition=self.definition,
            rights_policy=self.rights,
            calendar=self.calendar(),
            knowledge_time_ns=3_000,
        )
        second = build_close_return_features(
            bars,
            definition=self.definition,
            rights_policy=self.rights,
            calendar=self.calendar(),
            knowledge_time_ns=3_000,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        point = first[0]
        self.assertEqual(point.value, Decimal("0.100000"))
        self.assertEqual(point.economic_time_ns, 2_000)
        self.assertEqual(point.available_to_strategy_at_ns, 2_300)
        self.assertEqual(point.definition_sha256, self.definition.sha256())
        self.assertEqual(point.rights_policy_sha256, self.rights.sha256())
        self.assertEqual(len(point.input_bar_sha256), 2)

    def test_late_bar_and_calendar_revision_change_only_later_views(self) -> None:
        bars = (
            self.bar(1_000, 1_500, "100", available_ns=2_200, input_suffix="1"),
            self.bar(1_500, 2_000, "110", available_ns=3_200, input_suffix="2"),
        )
        calendar = self.calendar(early_close_available_ns=3_500)
        self.assertEqual(
            build_close_return_features(
                bars,
                definition=self.definition,
                rights_policy=self.rights,
                calendar=calendar,
                knowledge_time_ns=3_000,
            ),
            (),
        )
        before_calendar_correction = build_close_return_features(
            bars,
            definition=self.definition,
            rights_policy=self.rights,
            calendar=calendar,
            knowledge_time_ns=3_300,
        )
        self.assertEqual(len(before_calendar_correction), 1)
        after_calendar_correction = build_close_return_features(
            bars,
            definition=self.definition,
            rights_policy=self.rights,
            calendar=calendar,
            knowledge_time_ns=4_000,
        )
        self.assertEqual(after_calendar_correction, ())

    def test_derivation_rights_and_input_rights_fail_closed(self) -> None:
        bars = (
            self.bar(1_000, 1_500, "100", input_suffix="1"),
            self.bar(1_500, 2_000, "101", input_suffix="2"),
        )
        with self.assertRaisesRegex(FeatureDerivationDenied, "FEATURE_DERIVATION_RIGHT_DENIED"):
            build_close_return_features(
                bars,
                definition=self.definition,
                rights_policy=self.policy(derived=False),
                calendar=self.calendar(),
                knowledge_time_ns=3_000,
            )
        wrong_rights = self.policy(derived=True)
        object.__setattr__(wrong_rights, "policy_id", "different-policy")
        with self.assertRaisesRegex(FeatureDerivationDenied, "FEATURE_DEFINITION_RIGHTS_MISMATCH"):
            build_close_return_features(
                bars,
                definition=self.definition,
                rights_policy=wrong_rights,
                calendar=self.calendar(),
                knowledge_time_ns=3_000,
            )
        tampered_bar = self.bar(1_500, 2_000, "101", input_suffix="3")
        object.__setattr__(tampered_bar, "rights_policy_sha256", "f" * 64)
        with self.assertRaisesRegex(FeatureDerivationDenied, "FEATURE_INPUT_RIGHTS_MISMATCH"):
            build_close_return_features(
                (bars[0], tampered_bar),
                definition=self.definition,
                rights_policy=self.rights,
                calendar=self.calendar(),
                knowledge_time_ns=3_000,
            )

    def test_feature_store_is_append_only_bitemporal_and_hash_verified(self) -> None:
        path = self.temp / "features.sqlite"
        store = FeatureStore(path)
        self.addCleanup(store.close)
        point = FeaturePoint(
            point_id="point-1",
            version=1,
            feature_id="close-return",
            feature_version=1,
            listing_id=LISTING_ID,
            economic_time_ns=2_000,
            available_to_strategy_at_ns=2_300,
            value=Decimal("0.100000"),
            definition_sha256=self.definition.sha256(),
            rights_policy_sha256=self.rights.sha256(),
            input_root_sha256="c" * 64,
            input_bar_sha256=("1" * 64, "2" * 64),
        )
        self.assertTrue(store.append(point))
        self.assertFalse(store.append(point))
        self.assertIsNone(store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=2_299))
        self.assertEqual(store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=2_300), point)
        with self.assertRaises(DuplicateConflict):
            store.append(
                FeaturePoint(
                    **{
                        **point.as_kwargs(),
                        "value": Decimal("0.200000"),
                    }
                )
            )
        connection = sqlite3.connect(path)
        connection.execute(
            "UPDATE feature_points SET value_text = ? WHERE point_id = ? AND version = ?",
            ("0.900000", "point-1", 1),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "FEATURE_POINT_HASH_MISMATCH"):
            store.history("point-1")

    def test_feature_revision_uses_latest_known_semantics(self) -> None:
        store = FeatureStore(self.temp / "revisions.sqlite")
        self.addCleanup(store.close)
        common = dict(
            point_id="point-1",
            feature_id="close-return",
            feature_version=1,
            listing_id=LISTING_ID,
            economic_time_ns=2_000,
            definition_sha256=self.definition.sha256(),
            rights_policy_sha256=self.rights.sha256(),
            input_root_sha256="c" * 64,
            input_bar_sha256=("1" * 64, "2" * 64),
        )
        v1 = FeaturePoint(version=1, available_to_strategy_at_ns=2_300, value=Decimal("0.100000"), **common)
        v2 = FeaturePoint(version=2, available_to_strategy_at_ns=3_300, value=Decimal("0.090000"), **common)
        store.append(v1)
        store.append(v2)
        self.assertEqual(store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=3_000), v1)
        self.assertEqual(store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=4_000), v2)


if __name__ == "__main__":
    unittest.main()
