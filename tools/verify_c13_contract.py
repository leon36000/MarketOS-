#!/usr/bin/env python3
"""Verify the bounded, non-promotable C13-0 runtime contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_checks(root: Path) -> dict[str, bool]:
    sys.path.insert(0, str(root / "src"))
    from marketos.authoritative_books import (
        C13RiskGate,
        DurableLedger,
        ReconciliationStatus,
        reconcile_book,
    )
    from marketos.money import Money, Price, Quantity
    from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
    from marketos.portfolio import PortfolioBook
    from marketos.risk import RiskAction, RiskContext, RiskKernel, RiskLimits
    from marketos.time import ClockQuality

    with tempfile.TemporaryDirectory(prefix="marketos-c13-verify-") as directory:
        path = Path(directory) / "books.sqlite"
        with DurableLedger(path) as ledger:
            book = PortfolioBook(base_currency="USD", ledger=ledger)
            book.fund(
                "funding-1",
                Money.from_decimal("USD", "5000.00"),
                occurred_at_ns=100,
            )
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", snapshot, captured_at_ns=200)
            ledger_verified = ledger.verify()
            reconciliation = reconcile_book(ledger, snapshot)
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
                books_reconciled=True,
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
            return {
                "ledger_replays": bool(ledger_verified and ledger.entries()),
                "reconciled_checkpoint": reconciliation.status is ReconciliationStatus.RECONCILED,
                "paper_allow": gate.action is RiskAction.ALLOW,
                "divergence_veto": veto.action is RiskAction.NO_TRADE
                and "BOOKS_UNRECONCILED" in veto.reasons,
                "live_lock": gate.live_trading_state == "HARD_LOCKED",
            }


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
    ]
    checks["required_artifacts"] = all((root / path).is_file() for path in required)
    if not checks["required_artifacts"]:
        errors.extend(f"MISSING_ARTIFACT:{path}" for path in required if not (root / path).is_file())

    decisions: dict[str, Any] = {}
    closure: dict[str, Any] = {}
    state: dict[str, Any] = {}
    reconciliation: dict[str, Any] = {}
    try:
        decisions = _load(root / "planning/phases/C13/C13_DECISIONS.json")
        closure = _load(root / "planning/phases/C13/C13_REQUIREMENT_CLOSURE.json")
        state = _load(root / "authority/CURRENT_STATE.json")
        reconciliation = _load(root / "planning/architecture/PR14_PR20_RECONCILIATION.json")
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
