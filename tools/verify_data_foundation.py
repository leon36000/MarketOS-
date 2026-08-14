#!/usr/bin/env python3
"""Independent acceptance verifier for Security Master and local Data Fabric."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Callable
from uuid import UUID

from marketos.corporate_actions import (
    ActionFamily,
    ActionStatus,
    CorporateActionBook,
    CorporateActionVersion,
)
from marketos.datafabric import (
    DatasetPublisher,
    DatasetSpec,
    PublicationDenied,
    RawEvidenceStore,
    TemporalFact,
    TemporalFactStore,
    create_backup_manifest,
    verify_backup_manifest,
)
from marketos.identity import (
    IdentifierAssignment,
    IdentifierType,
    Instrument,
    ListingStatus,
    ListingVersion,
    SecurityMaster,
    Venue,
)
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy


INSTRUMENT_A = UUID("00000000-0000-0000-0000-000000002001")
INSTRUMENT_B = UUID("00000000-0000-0000-0000-000000002002")
VENUE_ID = UUID("00000000-0000-0000-0000-000000002010")
LISTING_A = UUID("00000000-0000-0000-0000-000000002100")
LISTING_B = UUID("00000000-0000-0000-0000-000000002101")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def _rights() -> RightsPolicy:
    fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
    for field in ("storage", "historical_replay", "derived_data", "audit_reporting", "exit_export"):
        fields[field] = RightDecision.ALLOW
    return RightsPolicy("rights-acceptance", fields)


def verify_data_foundation() -> dict[str, object]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def run(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
            checks[name] = True
        except Exception as exc:  # verifier must preserve every failed check
            checks[name] = False
            errors.append(f"{name}:{type(exc).__name__}:{exc}")

    with tempfile.TemporaryDirectory(prefix="marketos-data-foundation-") as temp_dir:
        root = Path(temp_dir)

        def rights_check() -> None:
            policy = _rights()
            _require(policy.allows("storage"), "STORAGE_NOT_ALLOWED")
            _require(not policy.allows("model_training"), "TRAINING_SHOULD_BE_DENIED")
            _require(not policy.allows("invented_capability"), "UNKNOWN_RIGHT_NOT_DENIED")
            _require(policy.live_trading_state == "HARD_LOCKED", "RIGHTS_WEAKENED_LIVE_LOCK")

        run("rights_fail_closed", rights_check)

        def identity_check() -> None:
            master = SecurityMaster()
            master.add_instrument(Instrument(INSTRUMENT_A, "EQUITY", "USD"))
            master.add_instrument(Instrument(INSTRUMENT_B, "EQUITY", "USD"))
            master.add_venue(Venue(VENUE_ID, "XNAS", "Nasdaq"))
            old = ListingVersion(
                LISTING_A, 1, INSTRUMENT_A, VENUE_ID, "ABC", ListingStatus.DELISTED,
                0, 100, 10, 10, 10,
            )
            new = ListingVersion(
                LISTING_B, 1, INSTRUMENT_B, VENUE_ID, "ABC", ListingStatus.ACTIVE,
                100, None, 120, 120, 120,
            )
            master.append_listing(old)
            master.append_listing(new)
            _require(
                master.resolve_symbol("ABC", "XNAS", economic_time_ns=50, knowledge_time_ns=130).listing_id == LISTING_A,
                "OLD_SYMBOL_HISTORY_LOST",
            )
            _require(
                master.resolve_symbol("ABC", "XNAS", economic_time_ns=150, knowledge_time_ns=110) is None,
                "FUTURE_LISTING_VISIBLE",
            )
            assignment = IdentifierAssignment(
                UUID("00000000-0000-0000-0000-000000002200"), 1, LISTING_B,
                IdentifierType.VENDOR_SYMBOL, "ABC.OQ", 100, None, 125, 125, 125,
            )
            master.append_identifier(assignment)
            _require(
                master.resolve_identifier(
                    IdentifierType.VENDOR_SYMBOL,
                    "ABC.OQ",
                    economic_time_ns=150,
                    knowledge_time_ns=130,
                ).entity_id == LISTING_B,
                "LISTING_IDENTIFIER_NOT_RESOLVED",
            )

        run("bitemporal_security_master", identity_check)

        def action_check() -> None:
            book = CorporateActionBook()
            action_id = UUID("00000000-0000-0000-0000-000000002300")
            common = dict(
                action_id=action_id,
                instrument_id=INSTRUMENT_A,
                family=ActionFamily.SPLIT,
                announcement_ns=20,
                ex_date_ns=100,
                record_date_ns=110,
                effective_date_ns=100,
                payable_date_ns=None,
                expiration_date_ns=None,
                source_id="exchange",
                terms={"new_shares": "2", "old_shares": "1"},
            )
            announced = CorporateActionVersion(
                version=1,
                status=ActionStatus.ANNOUNCED,
                first_seen_at_ns=30,
                available_to_strategy_at_ns=30,
                revision_time_ns=30,
                **common,
            )
            cancelled = CorporateActionVersion(
                version=2,
                status=ActionStatus.CANCELLED,
                first_seen_at_ns=50,
                available_to_strategy_at_ns=50,
                revision_time_ns=50,
                **common,
            )
            book.append(announced)
            book.append(cancelled)
            _require(book.as_known(action_id, knowledge_time_ns=40) == announced, "ACTION_HISTORY_LOST")
            _require(book.effective_between(0, 200, knowledge_time_ns=60) == (), "CANCELLED_ACTION_EFFECTIVE")

        run("corporate_action_revisions", action_check)

        def raw_check() -> None:
            with RawEvidenceStore(root / "raw") as store:
                first = store.put(
                    b"primary-source-bytes",
                    source_id="exchange",
                    retrieved_at_ns=10,
                    media_type="application/octet-stream",
                    rights_policy_ids=("rights-acceptance",),
                )
                second = store.put(
                    b"primary-source-bytes",
                    source_id="exchange",
                    retrieved_at_ns=20,
                    media_type="application/octet-stream",
                    rights_policy_ids=("rights-acceptance",),
                )
                _require(first.inserted and not second.inserted, "RAW_IDEMPOTENCY_FAILED")
                _require(len(store.receipts(first.content_sha256)) == 2, "RETRIEVAL_AUDIT_LOST")
                _require(store.verify(first.content_sha256), "RAW_HASH_VERIFY_FAILED")
                first.object_path.write_bytes(b"tampered")
                _require(not store.verify(first.content_sha256), "RAW_TAMPER_NOT_DETECTED")

        run("raw_evidence_integrity", raw_check)

        def fact_check() -> None:
            with TemporalFactStore(root / "facts.sqlite") as store:
                v1 = TemporalFact("fact-1", "issuer:1:status", 1, 0, None, 10, 10, "source", {"status": "ACTIVE"})
                v2 = TemporalFact("fact-1", "issuer:1:status", 2, 0, None, 20, 20, "source", {"status": "DELISTED"})
                store.append(v1)
                store.append(v2)
                _require(store.as_of("issuer:1:status", economic_time_ns=5, knowledge_time_ns=15) == v1, "FACT_LOOKAHEAD")
                _require(store.as_of("issuer:1:status", economic_time_ns=5, knowledge_time_ns=25) == v2, "FACT_REVISION_MISSING")

        run("bitemporal_fact_truth", fact_check)

        def publication_check() -> None:
            publisher = DatasetPublisher(root / "lake")
            policy = _rights()
            spec = DatasetSpec(
                "security-master", "v1", "security-master@1", ("source@1",),
                100, 110, "a" * 64, "b" * 64, "c" * 64,
                (policy.policy_id,), "quality-1", "lineage-1",
            )
            try:
                publisher.publish(
                    spec,
                    {"part-000.jsonl": b'{"id":1}\n'},
                    rights_policies=(policy,),
                    quality_pass=False,
                    lineage_complete=True,
                )
            except PublicationDenied:
                pass
            else:
                raise AssertionError("QUALITY_GATE_DID_NOT_BLOCK")
            _require(publisher.list_versions("security-master") == (), "PARTIAL_DATASET_VISIBLE")
            first = publisher.publish(
                spec,
                {"part-000.jsonl": b'{"id":1}\n'},
                rights_policies=(policy,),
                quality_pass=True,
                lineage_complete=True,
            )
            second = publisher.publish(
                spec,
                {"part-000.jsonl": b'{"id":1}\n'},
                rights_policies=(policy,),
                quality_pass=True,
                lineage_complete=True,
            )
            _require(first.inserted and not second.inserted, "DATASET_IDEMPOTENCY_FAILED")
            _require(first.content_root_sha256 == second.content_root_sha256, "DATASET_ROOT_CHANGED")

        run("atomic_dataset_publication", publication_check)

        def backup_check() -> None:
            source = root / "restore-source"
            source.mkdir()
            (source / "a.txt").write_text("alpha", encoding="utf-8")
            manifest = create_backup_manifest(source)
            _require(verify_backup_manifest(source, manifest).ok, "CLEAN_BACKUP_VERIFY_FAILED")
            (source / "a.txt").write_text("corrupt", encoding="utf-8")
            _require(not verify_backup_manifest(source, manifest).ok, "BACKUP_CORRUPTION_NOT_DETECTED")

        run("backup_semantic_verification", backup_check)

        def boundary_check() -> None:
            _require(SecurityMaster.live_trading_state == "HARD_LOCKED", "IDENTITY_LIVE_LOCK")
            _require(CorporateActionBook.live_trading_state == "HARD_LOCKED", "ACTION_LIVE_LOCK")
            _require(RawEvidenceStore.live_trading_state == "HARD_LOCKED", "RAW_LIVE_LOCK")
            _require(TemporalFactStore.live_trading_state == "HARD_LOCKED", "FACT_LIVE_LOCK")
            _require(DatasetPublisher.live_trading_state == "HARD_LOCKED", "DATASET_LIVE_LOCK")

        run("authority_boundaries", boundary_check)

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
        "production_storage_engine_selected": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_data_foundation()
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
