#!/usr/bin/env python3
"""Independent acceptance verifier for venue calendars and point-in-time features."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Callable
from uuid import UUID

from marketos.bars import TradeBar
from marketos.canonical import canonical_sha256
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


LISTING_ID = UUID("00000000-0000-0000-0000-000000009100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000009010")
SESSION_ID = UUID("00000000-0000-0000-0000-000000009200")
INPUT_BARS = ("1" * 64, "2" * 64)
INPUT_SESSIONS = ("3" * 64,)
INPUT_ROOT = canonical_sha256(
    {"bars": INPUT_BARS, "sessions": INPUT_SESSIONS}
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def _rights(*, derived: bool = True) -> RightsPolicy:
    fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
    for field in ("non_display", "historical_replay"):
        fields[field] = RightDecision.ALLOW
    if derived:
        fields["derived_data"] = RightDecision.ALLOW
    return RightsPolicy("feature-rights", fields)


def _definition() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="close-return",
        version=1,
        family="TECHNICAL",
        lookback=1,
        output_scale=6,
        code_sha256="a" * 64,
        config_sha256="b" * 64,
        input_schema_ids=("trade-bar@1",),
        rights_policy_ids=("feature-rights",),
        null_policy="SKIP",
    )


def _calendar(*, early_close_available_ns: int | None = None) -> VenueCalendar:
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


def _bar(start_ns: int, end_ns: int, close: str, suffix: str, *, available_ns: int) -> TradeBar:
    price = Price.parse("USD", close, tick_size="0.01")
    rights = _rights()
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
        available_to_strategy_at_ns=available_ns,
        input_root_sha256=(suffix * 64)[:64],
        rights_policy_sha256=rights.sha256(),
    )


def verify_feature_foundation() -> dict[str, object]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def run(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
            checks[name] = True
        except Exception as exc:
            checks[name] = False
            errors.append(f"{name}:{type(exc).__name__}:{exc}")

    with tempfile.TemporaryDirectory(prefix="marketos-feature-acceptance-") as temp_dir:
        root = Path(temp_dir)

        def calendar_revision() -> None:
            calendar = _calendar(early_close_available_ns=3_500)
            _require(calendar.is_open(VENUE_ID, 1_750, knowledge_time_ns=3_000), "EARLY_CLOSE_LOOKAHEAD")
            _require(not calendar.is_open(VENUE_ID, 1_750, knowledge_time_ns=4_000), "EARLY_CLOSE_REVISION_MISSING")
            _require(calendar.is_open(VENUE_ID, 1_499, knowledge_time_ns=4_000), "OPEN_INTERVAL_WRONG")
            _require(not calendar.is_open(VENUE_ID, 1_500, knowledge_time_ns=4_000), "CLOSE_NOT_EXCLUSIVE")

        run("latest_known_session_boundaries", calendar_revision)

        def deterministic_feature() -> None:
            bars = (
                _bar(1_000, 1_500, "100", "1", available_ns=2_200),
                _bar(1_500, 2_000, "110", "2", available_ns=2_300),
            )
            first = build_close_return_features(
                tuple(reversed(bars)),
                definition=_definition(),
                rights_policy=_rights(),
                calendar=_calendar(),
                knowledge_time_ns=3_000,
            )
            second = build_close_return_features(
                bars,
                definition=_definition(),
                rights_policy=_rights(),
                calendar=_calendar(),
                knowledge_time_ns=3_000,
            )
            _require(first == second, "FEATURE_NONDETERMINISTIC")
            _require(len(first) == 1, "FEATURE_POINT_MISSING")
            _require(first[0].value == Decimal("0.100000"), "FEATURE_VALUE_WRONG")
            _require(first[0].available_to_strategy_at_ns == 2_300, "FEATURE_AVAILABLE_TIME_WRONG")

        run("deterministic_point_in_time_return", deterministic_feature)

        def late_input_and_calendar_cutoff() -> None:
            bars = (
                _bar(1_000, 1_500, "100", "1", available_ns=2_200),
                _bar(1_500, 2_000, "110", "2", available_ns=3_200),
            )
            calendar = _calendar(early_close_available_ns=3_500)
            _require(
                not build_close_return_features(
                    bars,
                    definition=_definition(),
                    rights_policy=_rights(),
                    calendar=calendar,
                    knowledge_time_ns=3_000,
                ),
                "LATE_BAR_LOOKAHEAD",
            )
            _require(
                len(
                    build_close_return_features(
                        bars,
                        definition=_definition(),
                        rights_policy=_rights(),
                        calendar=calendar,
                        knowledge_time_ns=3_300,
                    )
                )
                == 1,
                "LATE_BAR_NOT_VISIBLE_AFTER_ARRIVAL",
            )
            _require(
                not build_close_return_features(
                    bars,
                    definition=_definition(),
                    rights_policy=_rights(),
                    calendar=calendar,
                    knowledge_time_ns=4_000,
                ),
                "CALENDAR_CORRECTION_IGNORED",
            )

        run("late_inputs_and_calendar_cutoff", late_input_and_calendar_cutoff)

        def rights_gate() -> None:
            try:
                build_close_return_features(
                    (
                        _bar(1_000, 1_500, "100", "1", available_ns=2_200),
                        _bar(1_500, 2_000, "101", "2", available_ns=2_300),
                    ),
                    definition=_definition(),
                    rights_policy=_rights(derived=False),
                    calendar=_calendar(),
                    knowledge_time_ns=3_000,
                )
            except FeatureDerivationDenied:
                return
            raise AssertionError("FEATURE_RIGHTS_DID_NOT_BLOCK")

        run("feature_rights_fail_closed", rights_gate)

        def store_idempotency() -> None:
            with FeatureStore(root / "features.sqlite") as store:
                point = FeaturePoint(
                    point_id="point-1",
                    version=1,
                    feature_id="close-return",
                    feature_version=1,
                    listing_id=LISTING_ID,
                    economic_time_ns=2_000,
                    available_to_strategy_at_ns=2_300,
                    value=Decimal("0.100000"),
                    definition_sha256=_definition().sha256(),
                    rights_policy_sha256=_rights().sha256(),
                    input_root_sha256=INPUT_ROOT,
                    input_bar_sha256=INPUT_BARS,
                input_session_sha256=INPUT_SESSIONS,
                )
                _require(store.append(point), "FEATURE_FIRST_INSERT_FAILED")
                _require(not store.append(point), "FEATURE_IDEMPOTENCY_FAILED")
                _require(store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=2_299) is None, "FEATURE_FUTURE_VISIBLE")
                _require(store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=2_300) == point, "FEATURE_ASOF_MISSING")

        run("append_only_feature_store", store_idempotency)

        def store_revision() -> None:
            with FeatureStore(root / "revisions.sqlite") as store:
                common = dict(
                    point_id="point-1",
                    feature_id="close-return",
                    feature_version=1,
                    listing_id=LISTING_ID,
                    economic_time_ns=2_000,
                    definition_sha256=_definition().sha256(),
                    rights_policy_sha256=_rights().sha256(),
                    input_root_sha256=INPUT_ROOT,
                    input_bar_sha256=INPUT_BARS,
                input_session_sha256=INPUT_SESSIONS,
                )
                v1 = FeaturePoint(version=1, available_to_strategy_at_ns=2_300, value=Decimal("0.100000"), **common)
                v2 = FeaturePoint(version=2, available_to_strategy_at_ns=3_300, value=Decimal("0.090000"), **common)
                store.append(v1)
                store.append(v2)
                _require(store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=3_000) == v1, "FEATURE_REVISION_LOOKAHEAD")
                _require(store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=4_000) == v2, "FEATURE_REVISION_MISSING")

        run("latest_known_feature_revisions", store_revision)

        def stored_integrity() -> None:
            path = root / "tamper.sqlite"
            point = FeaturePoint(
                point_id="point-tamper",
                version=1,
                feature_id="close-return",
                feature_version=1,
                listing_id=LISTING_ID,
                economic_time_ns=2_000,
                available_to_strategy_at_ns=2_300,
                value=Decimal("0.100000"),
                definition_sha256=_definition().sha256(),
                rights_policy_sha256=_rights().sha256(),
                input_root_sha256=INPUT_ROOT,
                input_bar_sha256=INPUT_BARS,
                input_session_sha256=INPUT_SESSIONS,
            )
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
                try:
                    store.history(point.point_id)
                except Exception as exc:
                    _require("FEATURE_POINT_HASH_MISMATCH" in str(exc), "WRONG_FEATURE_TAMPER_DIAGNOSTIC")
                    return
            raise AssertionError("FEATURE_TAMPER_NOT_FOUND")

        run("stored_feature_integrity", stored_integrity)

        def authority_boundary() -> None:
            _require(VenueCalendar.live_trading_state == "HARD_LOCKED", "CALENDAR_LIVE_LOCK")
            _require(not VenueCalendar.provider_selected, "CALENDAR_PROVIDER_FALSELY_SELECTED")
            _require(FeatureStore.live_trading_state == "HARD_LOCKED", "FEATURE_LIVE_LOCK")
            _require(not FeatureStore.backend_selected, "FEATURE_BACKEND_FALSELY_SELECTED")
            _require(not FeatureStore.feature_edge_proven, "FEATURE_EDGE_FALSELY_PROVEN")

        run("authority_boundaries", authority_boundary)

    passed = sum(checks.values())
    return {
        "ok": not errors and passed == 8,
        "checks": checks,
        "checks_total": 8,
        "checks_passed": passed,
        "errors": errors,
        "live_trading_state": "HARD_LOCKED",
        "profitability_state": "UNPROVEN",
        "calendar_provider_selected": False,
        "feature_backend_selected": False,
        "feature_edge_proven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_feature_foundation()
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
