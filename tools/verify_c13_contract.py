#!/usr/bin/env python3
"""Verify the bounded, non-promotable C13-0 runtime contract."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any


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


C13_SOURCE_PATHS = (
    "docs/implementation/C13_AUTHORITATIVE_BOOKS_RISK_VETO.md",
    "docs/superpowers/plans/2026-08-20-c13-authoritative-books-risk-veto.md",
    "docs/superpowers/specs/2026-08-20-c13-authoritative-books-risk-veto-design.md",
    "planning/PHASE_INDEX.json",
    "planning/phases/C13/C13_DECISIONS.json",
    "planning/phases/C13/C13_REQUIREMENT_CLOSURE.json",
    "planning/phases/C13/EXECUTION_CONTRACT.md",
    "src/marketos/authoritative_books.py",
    "tests/test_c13_authoritative_books.py",
    "tools/verify_c13_contract.py",
)


def _runtime_checks(root: Path) -> dict[str, bool]:
    sys.path.insert(0, str(root / "src"))
    from marketos.authoritative_books import (
        BookReconciliation,
        C13RiskGate,
        DurableLedger,
        ReconciliationStatus,
        reconcile_book,
    )
    from marketos.canonical import canonical_sha256
    from marketos.ledger import JournalEntry, Posting, PostingSide
    from marketos.money import Money, Price, Quantity
    from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
    from marketos.risk import RiskAction, RiskContext, RiskKernel, RiskLimits
    from marketos.time import ClockQuality
    from marketos.errors import InvariantViolation

    with tempfile.TemporaryDirectory(prefix="marketos-c13-verify-") as directory:
        path = Path(directory) / "books.sqlite"
        with DurableLedger(path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund(
                "funding-1",
                Money.from_decimal("USD", "5000.00"),
                occurred_at_ns=100,
            )
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
            ledger_verified = ledger.verify()
            reconciliation = reconcile_book(ledger, snapshot)
            fake_snapshot = replace(snapshot, cash=Money.from_decimal("USD", "4999.00"))
            try:
                ledger.checkpoint("fake-checkpoint", fake_snapshot, captured_at_ns=201)
                snapshot_provenance = False
            except InvariantViolation:
                snapshot_provenance = True
            limits = RiskLimits(
                currency="USD",
                allowed_instruments=frozenset({"AAPL"}),
                max_order_notional=Money.from_decimal("USD", "10000"),
                max_gross_notional=Money.from_decimal("USD", "20000"),
                max_position_quantity=Quantity.positive("100"),
                max_data_age_ns=100,
                max_clock_sync_age_ns=500,
                max_clock_error_ns=50,
                allow_short=False,
            )
            intent = OrderIntent(
                intent_id="intent-1",
                client_order_id="client-1",
                idempotency_key="idem-1",
                instrument_id="AAPL",
                side=OrderSide.BUY,
                quantity=Quantity.positive("10"),
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force=TimeInForce.IOC,
                created_at_ns=900,
                valid_from_ns=900,
                expires_at_ns=2_000,
                strategy_version="strategy@1",
                config_sha256="a" * 64,
                mode=ExecutionMode.PAPER,
            )
            context = RiskContext(
                now_ns=1_000,
                data_available_at_ns=950,
                portfolio_snapshot_sha256="b" * 64,
                ledger_head_sha256="c" * 64,
                market_view_sha256="d" * 64,
                clock_quality=ClockQuality("chrony", "NTP", 900, 20, 5, "SYNCED"),
                cash=Money.from_decimal("USD", "5000"),
                current_position=Quantity.parse("0"),
                current_gross_notional=Money.zero("USD"),
                mark_price=Price.parse("USD", "100", tick_size="0.01"),
                estimated_fee=Money.from_decimal("USD", "1"),
            )
            decision = RiskKernel(limits).evaluate(intent, context)
            gate = C13RiskGate().evaluate(decision, reconciliation, ExecutionMode.PAPER)
            altered = snapshot.__class__(
                base_currency=snapshot.base_currency,
                cash=Money.from_decimal("USD", "4999.00"),
                positions=snapshot.positions,
                realized_pnl=snapshot.realized_pnl,
                ledger_sha256=snapshot.ledger_sha256,
            )
            divergent = reconcile_book(ledger, altered)
            veto = C13RiskGate().evaluate(decision, divergent, ExecutionMode.SHADOW)
            forged_status = replace(divergent, status=ReconciliationStatus.RECONCILED)
            status_veto = C13RiskGate().evaluate(
                decision,
                forged_status,
                ExecutionMode.PAPER,
            )
            forged_reasons: tuple[str, ...] = ()
            forged_expected_sha256 = canonical_sha256(
                {
                    "status": ReconciliationStatus.RECONCILED,
                    "journal_sha256": ledger.sha256(),
                    "book_sha256": snapshot.sha256(),
                    "reasons": forged_reasons,
                }
            )
            forged_reconciliation = BookReconciliation(
                status=ReconciliationStatus.RECONCILED,
                journal_sha256=ledger.sha256(),
                book_sha256=snapshot.sha256(),
                expected_sha256=forged_expected_sha256,
                reasons=forged_reasons,
            )
            fabricated_veto = C13RiskGate().evaluate(
                decision,
                forged_reconciliation,
                ExecutionMode.PAPER,
            )
            ledger.post(
                JournalEntry(
                    entry_id="funding-2",
                    occurred_at_ns=300,
                    description="second fund",
                    postings=(
                        Posting(
                            "asset:cash:USD",
                            PostingSide.DEBIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                        Posting(
                            "equity:capital:USD",
                            PostingSide.CREDIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                    ),
                )
            )
            stale_veto = C13RiskGate().evaluate(
                decision,
                reconciliation,
                ExecutionMode.PAPER,
            )
            malformed_decision = C13RiskGate().evaluate(
                object(),
                reconciliation,
                ExecutionMode.PAPER,
            )
            malformed_reconciliation = C13RiskGate().evaluate(
                decision,
                object(),
                ExecutionMode.PAPER,
            )
            runtime_checks = {
                "ledger_replays": bool(ledger_verified and ledger.entries()),
                "reconciled_checkpoint": reconciliation.status is ReconciliationStatus.RECONCILED,
                "paper_allow": gate.action is RiskAction.ALLOW,
                "divergence_veto": veto.action is RiskAction.NO_TRADE
                and "BOOKS_UNRECONCILED" in veto.reasons,
                "live_lock": gate.live_trading_state == "HARD_LOCKED",
                "snapshot_provenance": snapshot_provenance,
                "status_integrity_veto": status_veto.action is RiskAction.NO_TRADE
                and "RECONCILIATION_INTEGRITY_FAILURE" in status_veto.reasons,
                "fabricated_reconciliation_veto": fabricated_veto.action is RiskAction.NO_TRADE
                and "RECONCILIATION_INTEGRITY_FAILURE" in fabricated_veto.reasons,
                "stale_reconciliation_veto": stale_veto.action is RiskAction.NO_TRADE
                and "RECONCILIATION_INTEGRITY_FAILURE" in stale_veto.reasons,
                "malformed_decision_veto": malformed_decision.action is RiskAction.NO_TRADE
                and "INVALID_RISK_DECISION" in malformed_decision.reasons,
                "malformed_reconciliation_veto": malformed_reconciliation.action is RiskAction.NO_TRADE
                and "INVALID_BOOK_RECONCILIATION" in malformed_reconciliation.reasons,
            }
        connection = sqlite3.connect(path)
        connection.execute("DROP TRIGGER ledger_entries_no_delete")
        connection.execute(
            "DELETE FROM ledger_entries WHERE entry_id = ?",
            ("funding-1",),
        )
        connection.commit()
        connection.close()
        try:
            DurableLedger(path)
            runtime_checks["tail_anchor"] = False
        except InvariantViolation:
            runtime_checks["tail_anchor"] = True
        return runtime_checks


def verify_c13_contract(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    checks: dict[str, bool] = {}
    required = [
        "src/marketos/authoritative_books.py",
        "tests/test_c13_authoritative_books.py",
        "tools/verify_c13_contract.py",
        "docs/implementation/C13_AUTHORITATIVE_BOOKS_RISK_VETO.md",
        "planning/phases/C13/EXECUTION_CONTRACT.md",
        "planning/phases/C13/C13_DECISIONS.json",
        "planning/phases/C13/C13_REQUIREMENT_CLOSURE.json",
        "docs/superpowers/specs/2026-08-20-c13-authoritative-books-risk-veto-design.md",
        "planning/phases/C13/C13_SOURCE_RECEIPT.json",
        *C13_SOURCE_PATHS,
    ]
    checks["required_artifacts"] = all((root / path).is_file() for path in required)
    if not checks["required_artifacts"]:
        errors.extend(f"MISSING_ARTIFACT:{path}" for path in required if not (root / path).is_file())

    decisions: dict[str, Any] = {}
    closure: dict[str, Any] = {}
    state: dict[str, Any] = {}
    reconciliation: dict[str, Any] = {}
    source_receipt: dict[str, Any] = {}
    try:
        decisions = _load(root / "planning/phases/C13/C13_DECISIONS.json")
        closure = _load(root / "planning/phases/C13/C13_REQUIREMENT_CLOSURE.json")
        state = _load(root / "authority/CURRENT_STATE.json")
        reconciliation = _load(root / "planning/architecture/PR14_PR20_RECONCILIATION.json")
        source_receipt = _load(root / "planning/phases/C13/C13_SOURCE_RECEIPT.json")
    except Exception as exc:
        errors.append(f"INVALID_AUTHORITY_JSON:{exc}")

    contract_text = (root / "planning/phases/C13/EXECUTION_CONTRACT.md").read_text(
        encoding="utf-8"
    ) if (root / "planning/phases/C13/EXECUTION_CONTRACT.md").is_file() else ""
    checks["contract_is_partial"] = (
        "C13-0" in contract_text
        and "does not complete C13" in contract_text
        and "phase_complete = false" in contract_text
    )
    checks["decision_boundary"] = (
        decisions.get("phase") == "C13"
        and decisions.get("slice") == "C13-0"
        and decisions.get("status") == "VERIFIED_SLICE"
        and decisions.get("verification", {}).get("phase_complete") is False
        and decisions.get("verification", {}).get("promotion_allowed") is False
        and decisions.get("locks", {}).get("live_trading") == "HARD_LOCKED"
        and decisions.get("locks", {}).get("profitability") == "UNPROVEN"
    )
    closure_requirements = closure.get("requirements", [])
    closure_ids = {item.get("id") for item in closure_requirements if isinstance(item, dict)}
    checks["partial_requirement_boundary"] = (
        closure.get("phase") == "C13"
        and closure.get("slice") == "C13-0"
        and closure.get("status") == "VERIFIED_SLICE"
        and closure.get("hard_boundary", {}).get("phase_complete") is False
        and closure.get("hard_boundary", {}).get("promotion_allowed") is False
        and closure_ids == {
            "AUD-RSK-001",
            "AUD-RSK-004",
            "AUD-RSK-005",
            "AUD-RSK-006",
            "AUD-RSK-009",
        }
        and all(
            item.get("state") == "PARTIAL_VERIFIED_C13_0"
            for item in closure_requirements
            if isinstance(item, dict)
        )
    )
    checks["authority_locks"] = (
        state.get("live_trading_state") == "HARD_LOCKED"
        and state.get("profitability_state") == "UNPROVEN"
        and state.get("software_implementation_complete") is False
    )
    checks["critical_gaps_preserved"] = set(
        reconciliation.get("critical_open_gaps", [])
    ) == {
        "C13_RUNTIME_CONTRACTS",
        "C14_COCKPIT_AND_OPERABILITY",
        "C15_QUALIFICATION",
        "C16_PACKAGING_AND_INTEGRATION",
        "REQUIREMENTS_119_VS_108",
    }
    source_paths = source_receipt.get("source_paths", [])
    source_hashes = source_receipt.get("source_sha256", {})
    source_paths_valid = (
        isinstance(source_paths, list)
        and source_paths == list(C13_SOURCE_PATHS)
        and isinstance(source_hashes, dict)
        and list(source_hashes) == source_paths
        and "planning/phases/C13/C13_SOURCE_RECEIPT.json" not in source_paths
        and all(
            not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and Path(relative).as_posix() == relative
            for relative in source_paths
        )
    )
    source_hashes_match = source_paths_valid
    if source_paths_valid:
        for relative in source_paths:
            candidate = root / relative
            if not candidate.is_file() or _sha256(candidate) != source_hashes.get(relative):
                source_hashes_match = False
                errors.append(f"C13_SOURCE_HASH_MISMATCH:{relative}")
    source_parent_commit = source_receipt.get("source_parent_commit")
    source_parent_valid = False
    if isinstance(source_parent_commit, str) and len(source_parent_commit) == 40:
        try:
            git_result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", source_parent_commit, "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            source_parent_valid = git_result.returncode == 0
        except OSError:
            source_parent_valid = False
    checks["source_parent_commit"] = source_parent_valid
    if not source_parent_valid:
        errors.append("C13_SOURCE_PARENT_COMMIT_INVALID")
    checks["source_content_receipt"] = (
        source_receipt.get("version") == "1.0.0"
        and source_receipt.get("authority") == "C13_SOURCE_RECEIPT"
        and source_receipt.get("slice") == "C13-0"
        and source_receipt.get("content_addressed") is True
        and source_receipt.get("promotion_allowed") is False
        and source_hashes_match
        and source_receipt.get("source_tree_sha256") == _source_tree_sha256(source_hashes)
        and source_parent_valid
    )
    if not checks["source_content_receipt"]:
        errors.append("C13_SOURCE_RECEIPT_INVALID")
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
        "slice": "C13-0",
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
    report = verify_c13_contract(Path(args.root))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
