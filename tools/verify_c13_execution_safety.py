#!/usr/bin/env python3
"""Verify the bounded C13-1 pre-trade execution safety slice."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_checks(root: Path) -> tuple[dict[str, bool], list[str]]:
    sys.path.insert(0, str(root / "src"))
    from marketos.authoritative_books import DurableLedger
    from marketos.errors import ExecutionStateChanged, InvariantViolation
    from marketos.execution_safety import C13PreTradeEnvelope
    from marketos.money import Money, Price, Quantity
    from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderState, OrderType, TimeInForce
    from marketos.paper import MarketSnapshot, PaperBroker
    from marketos.risk import RiskKernel, RiskLimits
    from marketos.time import ClockQuality
    from marketos.ledger import JournalEntry, Posting, PostingSide

    def funding(entry_id: str) -> JournalEntry:
        amount = Money.from_decimal("USD", "1")
        return JournalEntry(
            entry_id=entry_id,
            occurred_at_ns=400,
            description="verification funding",
            postings=(
                Posting("asset:cash:USD", PostingSide.DEBIT, amount),
                Posting("equity:capital:USD", PostingSide.CREDIT, amount),
            ),
        )

    checks = {
        "paper_allow": False,
        "direct_submit_veto": False,
        "stale_head_veto": False,
        "sidecar_mismatch_veto": False,
        "reconstruction_veto": False,
    }
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="marketos-c13-1-verify-") as directory:
        path = Path(directory) / "books.sqlite"
        ledger = DurableLedger(path)
        try:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund", Money.from_decimal("USD", "1000"), occurred_at_ns=1)
            ledger.checkpoint("initial", book, captured_at_ns=2)
            limits = RiskLimits(
                currency="USD",
                allowed_instruments=frozenset({"AAPL"}),
                max_order_notional=Money.from_decimal("USD", "100000"),
                max_gross_notional=Money.from_decimal("USD", "100000"),
                max_position_quantity=Quantity.positive("1000"),
                max_data_age_ns=100,
                max_clock_sync_age_ns=500,
                max_clock_error_ns=50,
            )
            broker = PaperBroker(
                portfolio=book,
                risk_kernel=RiskKernel(limits),
                fee_bps="10",
                slippage_bps="0",
            )
            broker.update_market(
                MarketSnapshot(
                    "AAPL",
                    Price.parse("USD", "99", tick_size="0.01"),
                    Price.parse("USD", "100", tick_size="0.01"),
                    Quantity.parse("100"),
                    Quantity.parse("100"),
                    950,
                    "verification-quote",
                )
            )
            envelope = C13PreTradeEnvelope(broker=broker, book=book, ledger=ledger)
            clock = ClockQuality("verify", "DETERMINISTIC", 900, 0, 0, "SYNCED")

            intent = OrderIntent(
                "verify-order",
                "verify-client",
                "verify-idem",
                "AAPL",
                OrderSide.BUY,
                Quantity.positive("1"),
                OrderType.MARKET,
                None,
                TimeInForce.IOC,
                900,
                900,
                2_000,
                "verify@1",
                "a" * 64,
                ExecutionMode.PAPER,
            )
            report = envelope.submit(intent, now_ns=1_000, clock_quality=clock)
            checks["paper_allow"] = (
                report.state is OrderState.FILLED
                and bool(report.fills)
                and ledger.latest_checkpoint() is not None
                and ledger.latest_checkpoint().checkpoint_id == "c13-1:verify-idem"
            )

            try:
                broker.submit(None, now_ns=1_000, clock_quality=clock)
            except InvariantViolation as exc:
                checks["direct_submit_veto"] = str(exc) == "PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN"

            expected = ledger.sha256()
            writer = DurableLedger(path)
            try:
                writer.post(funding("outside"))
            finally:
                writer.close()
            try:
                with ledger.execution_transaction(expected):
                    pass
            except ExecutionStateChanged as exc:
                checks["stale_head_veto"] = str(exc) == "EXECUTION_STATE_CHANGED"

            ledger.anchor_path.write_text("{}", encoding="utf-8")
            sidecar_intent = replace(intent, intent_id="sidecar-order", idempotency_key="sidecar-idem")
            sidecar_report = envelope.submit(
                sidecar_intent,
                now_ns=1_000,
                clock_quality=clock,
            )
            checks["sidecar_mismatch_veto"] = (
                sidecar_report.state is OrderState.REJECTED
                and "RECONCILIATION_INTEGRITY_FAILURE" in sidecar_report.reasons
            )
        finally:
            ledger.close()

        reconstruction_path = Path(directory) / "reconstruction.sqlite"
        with DurableLedger(reconstruction_path) as nonempty:
            nonempty.post(funding("nonempty"))
            try:
                nonempty.authoritative_book(base_currency="USD")
            except InvariantViolation as exc:
                checks["reconstruction_veto"] = str(exc) == "BOOK_RECONSTRUCTION_REQUIRED"

    errors.extend(f"RUNTIME_CHECK_FAILED:{name}" for name, value in checks.items() if not value)
    return checks, errors


def verify_c13_execution_safety(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    required = [
        "src/marketos/execution_safety.py",
        "src/marketos/paper.py",
        "src/marketos/risk.py",
        "tests/test_c13_execution_safety.py",
        "tools/verify_c13_execution_safety.py",
        "docs/implementation/C13_1_PRE_TRADE_EXECUTION_SAFETY.md",
        "planning/phases/C13/C13_1_EXECUTION_CONTRACT.md",
        "planning/phases/C13/C13_1_DECISIONS.json",
        "planning/phases/C13/C13_1_REQUIREMENT_CLOSURE.json",
        "authority/CURRENT_STATE.json",
    ]
    checks = {"required_artifacts": all((root / path).is_file() for path in required)}
    errors.extend(f"MISSING_ARTIFACT:{path}" for path in required if not (root / path).is_file())

    decisions: dict[str, Any] = {}
    closure: dict[str, Any] = {}
    state: dict[str, Any] = {}
    contract = ""
    implementation = ""
    try:
        decisions = _load(root / "planning/phases/C13/C13_1_DECISIONS.json")
        closure = _load(root / "planning/phases/C13/C13_1_REQUIREMENT_CLOSURE.json")
        state = _load(root / "authority/CURRENT_STATE.json")
        contract = (root / "planning/phases/C13/C13_1_EXECUTION_CONTRACT.md").read_text(encoding="utf-8")
        implementation = (root / "docs/implementation/C13_1_PRE_TRADE_EXECUTION_SAFETY.md").read_text(encoding="utf-8")
    except Exception as exc:
        errors.append(f"INVALID_C13_1_ARTIFACT:{exc}")

    requirement_ids = [item.get("id") for item in closure.get("requirements", []) if isinstance(item, dict)]
    checks["decision_boundary"] = (
        decisions.get("phase") == "C13"
        and decisions.get("slice") == "C13-1"
        and decisions.get("status") == "VERIFIED_SLICE"
        and decisions.get("verification", {}).get("phase_complete") is False
        and decisions.get("verification", {}).get("promotion_allowed") is False
    )
    checks["partial_requirement_boundary"] = (
        set(requirement_ids)
        == {"AUD-RSK-001", "AUD-RSK-002", "AUD-RSK-004", "AUD-RSK-005", "AUD-RSK-009"}
        and closure.get("status") == "VERIFIED_SLICE"
        and closure.get("hard_boundary", {}).get("phase_complete") is False
        and all(
            item.get("state") == "PARTIAL_VERIFIED_C13_1"
            for item in closure.get("requirements", [])
            if isinstance(item, dict)
        )
    )
    checks["authority_locks"] = (
        state.get("live_trading_state") == "HARD_LOCKED"
        and state.get("profitability_state") == "UNPROVEN"
        and state.get("software_implementation_complete") is False
    )
    checks["reconstruction_scope"] = (
        "BOOK_RECONSTRUCTION_REQUIRED" in contract
        and "no restart reconstruction" in contract.lower()
    )
    checks["simultaneous_witness_scope"] = (
        "simultaneous" in contract.lower()
        and "witness" in contract.lower()
        and "out of scope" in contract.lower()
    )
    checks["paper_shadow_only"] = (
        "PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN" in implementation
        and "PAPER" in implementation
        and "SHADOW" in implementation
        and "HARD_LOCKED" in implementation
    )
    runtime_checks, runtime_errors = _runtime_checks(root) if checks["required_artifacts"] else ({}, [])
    checks.update(runtime_checks)
    errors.extend(runtime_errors)

    return {
        "ok": not errors and all(checks.values()),
        "errors": errors,
        "checks": checks,
        "phase": "C13",
        "slice": "C13-1",
        "status": "VERIFIED_SLICE",
        "partial_requirements": requirement_ids,
        "phase_complete": False,
        "promotion_allowed": False,
        "live_trading_state": state.get("live_trading_state", "HARD_LOCKED"),
        "profitability_state": state.get("profitability_state", "UNPROVEN"),
        "restart_reconstruction_blocked": checks.get("reconstruction_scope", False),
        "simultaneous_db_witness_rewrite_excluded": checks.get("simultaneous_witness_scope", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_c13_execution_safety(Path(args.root))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
