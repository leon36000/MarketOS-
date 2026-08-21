#!/usr/bin/env python3
"""Verify the bounded, non-promotable C13-2 restart reconstruction slice."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any


C13_2_SOURCE_PATHS = (
    "docs/implementation/C13_2_CHECKPOINT_AUTHENTICATED_RESTART.md",
    "docs/superpowers/plans/2026-08-21-c13-2-checkpoint-authenticated-restart-plan.md",
    "docs/superpowers/specs/2026-08-21-c13-2-checkpoint-authenticity-reconstruction-design.md",
    "planning/phases/C13/C13_2_DECISIONS.json",
    "planning/phases/C13/C13_2_REQUIREMENT_CLOSURE.json",
    "planning/phases/C13/C13_2_EXECUTION_CONTRACT.md",
    "src/marketos/authoritative_books.py",
    "tests/test_c13_authoritative_books.py",
    "tools/verify_c13_checkpoint_reconstruction.py",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_tree_sha256(source_hashes: dict[str, str]) -> str:
    encoded = json.dumps(
        source_hashes,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_checks(root: Path) -> dict[str, bool]:
    sys.path.insert(0, str(root / "src"))
    from marketos.authoritative_books import DurableLedger
    from marketos.canonical import canonical_json, canonical_sha256
    from marketos.errors import InvariantViolation
    from marketos.money import Money

    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="marketos-c13-2-verify-") as directory:
        base = Path(directory)
        restore_path = base / "restore.sqlite"
        with DurableLedger(restore_path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            expected = book.snapshot()
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
        with DurableLedger(restore_path) as reopened:
            restored = reopened.authoritative_book(base_currency="USD")
            checks["current_head_restore"] = restored.snapshot() == expected

        missing_path = base / "missing.sqlite"
        with DurableLedger(missing_path):
            pass
        missing_path.with_name(missing_path.name + ".anchor.json").unlink()
        try:
            DurableLedger(missing_path)
            checks["existing_db_missing_sidecar"] = False
        except InvariantViolation as exc:
            checks["existing_db_missing_sidecar"] = str(exc) == "JOURNAL_INTEGRITY_FAILURE"

        orphan_path = base / "orphan.sqlite"
        with DurableLedger(orphan_path):
            pass
        orphan_anchor = orphan_path.with_name(orphan_path.name + ".anchor.json")
        orphan_path.unlink()
        try:
            DurableLedger(orphan_path)
            checks["orphaned_sidecar_rejected"] = False
        except InvariantViolation as exc:
            checks["orphaned_sidecar_rejected"] = str(exc) == "JOURNAL_INTEGRITY_FAILURE"
        checks["orphan_anchor_preserved"] = orphan_anchor.is_file()

        legacy_path = base / "legacy.sqlite"
        with DurableLedger(legacy_path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
        legacy_anchor = legacy_path.with_name(legacy_path.name + ".anchor.json")
        current = _load(legacy_anchor)
        legacy_payload = {
            key: current[key]
            for key in (
                "head_sequence",
                "ledger_entry_count",
                "head_record_sha256",
                "head_ledger_sha256",
            )
        }
        legacy_payload["anchor_sha256"] = canonical_sha256(legacy_payload)
        legacy_anchor.write_text(canonical_json(legacy_payload), encoding="utf-8")
        with DurableLedger(legacy_path) as reopened:
            try:
                reopened.authoritative_book(base_currency="USD")
                checks["legacy_restore_blocked"] = False
            except InvariantViolation as exc:
                checks["legacy_restore_blocked"] = str(exc) == "BOOK_CHECKPOINT_WITNESS_REQUIRED"

        tamper_path = base / "tamper.sqlite"
        with DurableLedger(tamper_path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
        connection = sqlite3.connect(tamper_path)
        connection.execute("DROP TRIGGER book_checkpoints_no_update")
        record_json = str(
            connection.execute(
                "SELECT record_json FROM book_checkpoints WHERE checkpoint_id = ?",
                ("checkpoint-1",),
            ).fetchone()[0]
        )
        record = json.loads(record_json)
        record["snapshot"]["cash"]["minor_units"] = 9900
        rewritten = canonical_json(record)
        connection.execute(
            "UPDATE book_checkpoints SET record_json = ?, record_sha256 = ? "
            "WHERE checkpoint_id = ?",
            (rewritten, canonical_sha256(record), "checkpoint-1"),
        )
        connection.commit()
        connection.close()
        try:
            DurableLedger(tamper_path)
            checks["checkpoint_witness_rejects_rewrite"] = False
        except InvariantViolation as exc:
            checks["checkpoint_witness_rejects_rewrite"] = str(exc) == "BOOK_CHECKPOINT_WITNESS_FAILURE"

        capture_path = base / "capture.sqlite"
        with DurableLedger(capture_path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            try:
                ledger.checkpoint("checkpoint-1", book, captured_at_ns=99)
                checks["capture_time_invariant"] = False
            except InvariantViolation as exc:
                checks["capture_time_invariant"] = str(exc) == "INVALID_BOOK_CHECKPOINT_TIME"
    return checks


def verify_c13_checkpoint_reconstruction(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    checks: dict[str, bool] = {}
    required = [*C13_2_SOURCE_PATHS, "planning/phases/C13/C13_2_SOURCE_RECEIPT.json"]
    checks["required_artifacts"] = all((root / path).is_file() for path in required)
    if not checks["required_artifacts"]:
        errors.extend(f"MISSING_ARTIFACT:{path}" for path in required if not (root / path).is_file())

    decisions: dict[str, Any] = {}
    closure: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    state: dict[str, Any] = {}
    try:
        decisions = _load(root / "planning/phases/C13/C13_2_DECISIONS.json")
        closure = _load(root / "planning/phases/C13/C13_2_REQUIREMENT_CLOSURE.json")
        receipt = _load(root / "planning/phases/C13/C13_2_SOURCE_RECEIPT.json")
        state = _load(root / "authority/CURRENT_STATE.json")
    except Exception as exc:
        errors.append(f"INVALID_C13_2_JSON:{exc}")

    contract = root / "planning/phases/C13/C13_2_EXECUTION_CONTRACT.md"
    contract_text = contract.read_text(encoding="utf-8") if contract.is_file() else ""
    checks["contract_is_bounded"] = (
        "C13-2" in contract_text
        and "does not complete C13" in contract_text
        and "HARD_LOCKED" in contract_text
        and "BOOK_CHECKPOINT_WITNESS_FAILURE" in contract_text
    )
    checks["decision_boundary"] = (
        decisions.get("phase") == "C13"
        and decisions.get("slice") == "C13-2"
        and decisions.get("status") == "VERIFIED_SLICE"
        and decisions.get("phase_complete") is False
        and decisions.get("promotion_allowed") is False
        and decisions.get("live_trading") == "HARD_LOCKED"
        and decisions.get("profitability") == "UNPROVEN"
    )
    checks["closure_boundary"] = (
        closure.get("phase") == "C13"
        and closure.get("slice") == "C13-2"
        and closure.get("status") == "VERIFIED_SLICE"
        and closure.get("phase_complete") is False
        and closure.get("promotion_allowed") is False
    )
    checks["authority_locks"] = (
        state.get("live_trading_state") == "HARD_LOCKED"
        and state.get("profitability_state") == "UNPROVEN"
        and state.get("software_implementation_complete") is False
    )

    source_paths = receipt.get("source_paths", [])
    source_hashes = receipt.get("source_sha256", {})
    source_paths_valid = (
        source_paths == list(C13_2_SOURCE_PATHS)
        and list(source_hashes) == list(C13_2_SOURCE_PATHS)
        and "planning/phases/C13/C13_2_SOURCE_RECEIPT.json" not in source_paths
    )
    source_hashes_match = source_paths_valid
    if source_paths_valid:
        for relative in source_paths:
            candidate = root / relative
            if not candidate.is_file() or _sha256(candidate) != source_hashes.get(relative):
                source_hashes_match = False
                errors.append(f"C13_2_SOURCE_HASH_MISMATCH:{relative}")
    source_parent = receipt.get("source_parent_commit")
    source_parent_valid = False
    if isinstance(source_parent, str) and len(source_parent) == 40:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_parent, "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        source_parent_valid = result.returncode == 0
    checks["source_receipt"] = (
        receipt.get("version") == "1.0.0"
        and receipt.get("authority") == "C13_2_SOURCE_RECEIPT"
        and receipt.get("slice") == "C13-2"
        and receipt.get("content_addressed") is True
        and receipt.get("promotion_allowed") is False
        and source_hashes_match
        and receipt.get("source_tree_sha256") == _source_tree_sha256(source_hashes)
        and source_parent_valid
    )
    if not checks["source_receipt"]:
        errors.append("C13_2_SOURCE_RECEIPT_INVALID")
    try:
        runtime = _runtime_checks(root)
        checks.update(runtime)
        errors.extend(f"RUNTIME_CHECK_FAILED:{name}" for name, passed in runtime.items() if not passed)
    except Exception as exc:
        checks["runtime_checks"] = False
        errors.append(f"RUNTIME_CHECK_ERROR:{type(exc).__name__}:{exc}")
    return {
        "ok": not errors and all(checks.values()),
        "errors": errors,
        "checks": checks,
        "phase": "C13",
        "slice": "C13-2",
        "phase_complete": False,
        "promotion_allowed": False,
        "live_trading_state": state.get("live_trading_state"),
        "profitability_state": state.get("profitability_state"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_c13_checkpoint_reconstruction(Path(args.root))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
