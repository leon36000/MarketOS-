#!/usr/bin/env python3
"""Independent acceptance verifier for canonical market-data ingestion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Callable
from uuid import UUID

from marketos.bars import build_trade_bars
from marketos.canonical import canonical_json
from marketos.datafabric import RawEvidenceStore
from marketos.marketdata import (
    IngestionDenied,
    MarketDataStore,
    MarketObservation,
    ObservationKind,
    ObservationStatus,
    QualityPolicy,
    QualityState,
    QuotePayload,
    TradePayload,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.time import EventTime


LISTING_ID = UUID("00000000-0000-0000-0000-000000005100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000005010")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def _rights(*, allow: bool = True) -> RightsPolicy:
    fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
    if allow:
        for field in ("storage", "non_display", "historical_replay", "derived_data"):
            fields[field] = RightDecision.ALLOW
    return RightsPolicy("market-rights", fields)


def _quality() -> QualityPolicy:
    return QualityPolicy(
        max_future_skew_ns=5,
        max_latency_ns=100,
        crossed_quote_action="QUARANTINE",
        zero_trade_price_action="QUARANTINE",
    )


def _quote(
    raw: RawEvidenceStore,
    observation_id: str,
    sequence: int,
    *,
    version: int = 1,
    status: ObservationStatus = ObservationStatus.ORIGINAL,
    bid: str = "99",
    ask: str = "100",
    event_ns: int = 100,
    receive_ns: int = 110,
    available_ns: int = 110,
) -> MarketObservation:
    raw_sha = raw.put(
        f"quote:{observation_id}:{version}".encode(),
        source_id="fixture-feed",
        retrieved_at_ns=max(0, receive_ns - 1),
        media_type="application/octet-stream",
        rights_policy_ids=("market-rights",),
    ).content_sha256
    return MarketObservation(
        observation_id=observation_id,
        version=version,
        kind=ObservationKind.QUOTE,
        status=status,
        listing_id=LISTING_ID,
        venue_id=VENUE_ID,
        source_id="fixture-feed",
        channel_id="quotes",
        source_sequence=sequence,
        time=EventTime(event_ns, available_ns, receive_ns, receive_ns),
        raw_content_sha256=raw_sha,
        schema_version="quote@1",
        payload=QuotePayload(
            bid=Price.parse("USD", bid, tick_size="0.01"),
            ask=Price.parse("USD", ask, tick_size="0.01"),
            bid_size=Quantity.parse("10"),
            ask_size=Quantity.parse("10"),
        ),
    )


def _trade(
    observation_id: str,
    sequence: int,
    *,
    event_ns: int,
    available_ns: int,
    price: str,
    size: str,
) -> MarketObservation:
    return MarketObservation(
        observation_id=observation_id,
        version=1,
        kind=ObservationKind.TRADE,
        status=ObservationStatus.ORIGINAL,
        listing_id=LISTING_ID,
        venue_id=VENUE_ID,
        source_id="fixture-feed",
        channel_id="trades",
        source_sequence=sequence,
        time=EventTime(event_ns, available_ns, available_ns, available_ns),
        raw_content_sha256=(f"{sequence:x}" * 64)[:64].ljust(64, "0"),
        schema_version="trade@1",
        payload=TradePayload(
            price=Price.parse("USD", price, tick_size="0.01"),
            size=Quantity.positive(size),
            condition_codes=(),
        ),
    )


def verify_market_data() -> dict[str, object]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def run(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
            checks[name] = True
        except Exception as exc:
            checks[name] = False
            errors.append(f"{name}:{type(exc).__name__}:{exc}")

    with tempfile.TemporaryDirectory(prefix="marketos-market-acceptance-") as temp_dir:
        root = Path(temp_dir)

        def canonical_contract() -> None:
            with RawEvidenceStore(root / "canonical-raw") as raw:
                observation = _quote(raw, "canonical", 1)
                _require(observation.sha256() == observation.sha256(), "UNSTABLE_OBSERVATION_HASH")
                _require(MarketDataStore.live_trading_state == "HARD_LOCKED", "LIVE_LOCK_WEAKENED")

        run("canonical_observation_contract", canonical_contract)

        def rights_gate() -> None:
            with RawEvidenceStore(root / "rights-raw") as raw, MarketDataStore(
                root / "rights.sqlite", raw_evidence_store=raw
            ) as store:
                try:
                    store.ingest(
                        _quote(raw, "denied", 1),
                        quality_policy=_quality(),
                        rights_policy=_rights(allow=False),
                    )
                except IngestionDenied:
                    return
                raise AssertionError("DENIED_RIGHTS_INGESTED")

        run("rights_fail_closed", rights_gate)

        def sequence_quality() -> None:
            with RawEvidenceStore(root / "sequence-raw") as raw, MarketDataStore(
                root / "sequence.sqlite", raw_evidence_store=raw
            ) as store:
                first = store.ingest(
                    _quote(raw, "q-1", 1),
                    quality_policy=_quality(),
                    rights_policy=_rights(),
                )
                gap = store.ingest(
                    _quote(raw, "q-3", 3),
                    quality_policy=_quality(),
                    rights_policy=_rights(),
                )
                collision = store.ingest(
                    _quote(raw, "q-other", 1),
                    quality_policy=_quality(),
                    rights_policy=_rights(),
                )
                _require(first.quality_state is QualityState.ACCEPTED, "FIRST_SEQUENCE_REJECTED")
                _require(any(reason.startswith("SEQUENCE_GAP") for reason in gap.reasons), "GAP_NOT_FOUND")
                _require("SEQUENCE_COLLISION" in collision.reasons, "COLLISION_NOT_FOUND")
                _require(len(store.stream(LISTING_ID, 0, 200, knowledge_time_ns=200)) == 1, "QUARANTINE_LEAK")

        run("sequence_and_quality_quarantine", sequence_quality)

        def raw_integrity() -> None:
            with RawEvidenceStore(root / "integrity-raw") as raw:
                ref = raw.put(
                    b"primary-feed-bytes",
                    source_id="fixture-feed",
                    retrieved_at_ns=10,
                    media_type="application/octet-stream",
                    rights_policy_ids=("market-rights",),
                )
                _require(raw.verify(ref.content_sha256), "RAW_VERIFY_FAILED")
                ref.object_path.write_bytes(b"tampered-feed-byte")
                _require(not raw.verify(ref.content_sha256), "RAW_TAMPER_NOT_FOUND")

        run("raw_evidence_integrity", raw_integrity)

        def correction_cutoff() -> None:
            with RawEvidenceStore(root / "correction-raw") as raw, MarketDataStore(
                root / "correction.sqlite", raw_evidence_store=raw
            ) as store:
                original = _quote(
                    raw,
                    "q",
                    1,
                    event_ns=50,
                    receive_ns=60,
                    available_ns=60,
                )
                corrected = _quote(
                    raw,
                    "q",
                    2,
                    version=2,
                    status=ObservationStatus.CORRECTED,
                    bid="98",
                    ask="99",
                    event_ns=50,
                    receive_ns=100,
                    available_ns=100,
                )
                cancelled = _quote(
                    raw,
                    "q",
                    3,
                    version=3,
                    status=ObservationStatus.CANCELLED,
                    bid="98",
                    ask="99",
                    event_ns=50,
                    receive_ns=150,
                    available_ns=150,
                )
                for observation in (original, corrected, cancelled):
                    store.ingest(
                        observation,
                        quality_policy=_quality(),
                        rights_policy=_rights(),
                    )
                _require(store.effective_as_known("q", knowledge_time_ns=80) == original, "ORIGINAL_CUTOFF_FAILED")
                _require(store.effective_as_known("q", knowledge_time_ns=120) == corrected, "CORRECTION_CUTOFF_FAILED")
                _require(store.effective_as_known("q", knowledge_time_ns=200) is None, "CANCELLATION_FAILED")

        run("correction_and_cancellation_cutoffs", correction_cutoff)

        def stored_tamper() -> None:
            path = root / "tamper.sqlite"
            with RawEvidenceStore(root / "tamper-raw") as raw, MarketDataStore(
                path, raw_evidence_store=raw
            ) as store:
                observation = _quote(raw, "tamper", 1)
                store.ingest(
                    observation,
                    quality_policy=_quality(),
                    rights_policy=_rights(),
                )
            replacement = canonical_json(
                QuotePayload(
                    bid=Price.parse("USD", "97", tick_size="0.01"),
                    ask=Price.parse("USD", "98", tick_size="0.01"),
                    bid_size=Quantity.parse("10"),
                    ask_size=Quantity.parse("10"),
                )
            )
            connection = sqlite3.connect(path)
            connection.execute(
                "UPDATE market_observations SET payload_json = ? WHERE observation_id = ? AND version = ?",
                (replacement, "tamper", 1),
            )
            connection.commit()
            connection.close()
            with RawEvidenceStore(root / "tamper-raw") as raw, MarketDataStore(
                path, raw_evidence_store=raw
            ) as store:
                try:
                    store.history("tamper")
                except Exception as exc:
                    _require("MARKET_OBSERVATION_HASH_MISMATCH" in str(exc), "WRONG_TAMPER_DIAGNOSTIC")
                    return
                raise AssertionError("STORED_TAMPER_NOT_FOUND")

        run("stored_observation_integrity", stored_tamper)

        def bar_cutoff() -> None:
            early = _trade("early", 1, event_ns=10, available_ns=20, price="100", size="2")
            middle = _trade("middle", 2, event_ns=20, available_ns=30, price="105", size="3")
            close = _trade("close", 3, event_ns=90, available_ns=95, price="102", size="1")
            late = _trade("late", 4, event_ns=80, available_ns=120, price="110", size="4")
            first = build_trade_bars(
                (close, late, early, middle),
                interval_ns=100,
                knowledge_time_ns=100,
            )
            second = build_trade_bars(
                (middle, early, close, late),
                interval_ns=100,
                knowledge_time_ns=100,
            )
            _require(first == second, "BAR_NONDETERMINISTIC")
            _require(first[0].high.value == 105, "LATE_TRADE_LOOKAHEAD")
            revised = build_trade_bars(
                (early, middle, close, late),
                interval_ns=100,
                knowledge_time_ns=130,
            )
            _require(revised[0].high.value == 110, "LATE_TRADE_NOT_APPLIED_AFTER_CUTOFF")
            _require(revised[0].input_root_sha256 != first[0].input_root_sha256, "BAR_LINEAGE_NOT_UPDATED")

        run("deterministic_point_in_time_bars", bar_cutoff)

        def authority_boundary() -> None:
            _require(not MarketDataStore.provider_selected, "PROVIDER_FALSELY_SELECTED")
            _require(not MarketDataStore.production_feed_qualified, "FEED_FALSELY_QUALIFIED")
            _require(MarketDataStore.live_trading_state == "HARD_LOCKED", "LIVE_LOCK_WEAKENED")

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
        "provider_selected": False,
        "production_feed_qualified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_market_data()
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
