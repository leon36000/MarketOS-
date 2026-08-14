#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "C13": {"AUD-MKT-013", "AUD-MKT-015", "AUD-AI-003", "AUD-AI-004", "AUD-DAT-012", "AUD-CMP-013", "AUD-UI-008", "AUD-UI-009", "AUD-RSK-001", "AUD-RSK-002", "AUD-RSK-003", "AUD-RSK-004", "AUD-RSK-005", "AUD-RSK-006", "AUD-RSK-009", "AUD-HOLO-002"},
    "C14": {"AUD-AI-002", "AUD-AI-003", "AUD-UI-001", "AUD-UI-002", "AUD-UI-003", "AUD-UI-004", "AUD-UI-005", "AUD-UI-006", "AUD-UI-007", "AUD-UI-008", "AUD-UI-009"},
    "C15": {"AUD-GOV-002", "AUD-GOV-003", "AUD-MKT-004", "AUD-DAT-001", "AUD-DAT-005", "AUD-DAT-006", "AUD-AI-006", "AUD-RSK-007", "AUD-RSK-008", "AUD-HOLO-001", "AUD-HOLO-002", "AUD-SOC-002"},
}


def _load(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected JSON object: {path}")
        return {}
    return value


def validate_c13_c15_design(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    decisions: dict[str, dict[str, Any]] = {}
    closures: dict[str, dict[str, Any]] = {}

    for phase in ("C13", "C14", "C15"):
        decisions[phase] = _load(root / f"planning/phases/{phase}/{phase}_DECISIONS.json", errors)
        closures[phase] = _load(root / f"planning/phases/{phase}/{phase}_REQUIREMENT_CLOSURE.json", errors)
        if decisions[phase].get("phase") != phase:
            errors.append(f"{phase} decision phase mismatch")
        if closures[phase].get("phase") != phase:
            errors.append(f"{phase} closure phase mismatch")
        if decisions[phase].get("status") not in {"CANDIDATE_PENDING_VERIFICATION", "DESIGN_GATE_PASS"}:
            errors.append(f"{phase} decision status invalid")
        if closures[phase].get("status") not in {"CANDIDATE_PENDING_VERIFICATION", "DESIGN_GATE_PASS"}:
            errors.append(f"{phase} closure status invalid")

        locks = decisions[phase].get("locks", {})
        if locks.get("live_trading") != "HARD_LOCKED":
            errors.append(f"{phase} live trading must remain HARD_LOCKED")
        if locks.get("profitability") != "UNPROVEN":
            errors.append(f"{phase} profitability must remain UNPROVEN")

        observed = set(closures[phase].get("requirement_ids", []))
        if observed != REQUIRED[phase]:
            errors.append(f"{phase} requirement set mismatch")
        for artifact in closures[phase].get("artifacts", []):
            if not (root / artifact).is_file():
                errors.append(f"{phase} missing artifact: {artifact}")
        boundary = closures[phase].get("hard_boundary", {})
        if boundary.get("live_trading") != "HARD_LOCKED" or boundary.get("profitability") != "UNPROVEN":
            errors.append(f"{phase} hard boundary invalid")

    c13 = decisions["C13"].get("locks", {})
    expected_c13 = {
        "risk_kernel_production_qualified": False,
        "broker_selected": False,
        "portfolio_solver_selected": False,
        "secret_manager_selected": False,
        "live_order_route": False,
        "model_can_override_risk_veto": "FORBIDDEN",
        "unreconciled_books_allow_risk_increase": False,
        "unknown_broker_capability_default": "DENY",
        "mutable_accounting_balances": "FORBIDDEN",
        "kill_switch_model_dependent": False,
        "secret_readback": "FORBIDDEN",
        "silent_reconciliation": "FORBIDDEN",
    }
    for key, expected in expected_c13.items():
        if c13.get(key) != expected:
            errors.append(f"C13 invariant failed: {key}")

    c14 = decisions["C14"].get("locks", {})
    expected_c14 = {
        "frontend_framework_selected": False,
        "auth_platform_selected": False,
        "secret_manager_selected": False,
        "cockpit_implemented": False,
        "material_claims_require_evidence": True,
        "pnl_equals_decision_quality": False,
        "browser_direct_broker_route": "FORBIDDEN",
        "secret_readback": "FORBIDDEN",
        "mobile_risk_increase": "FORBIDDEN",
        "delete_without_dependency_analysis": "FORBIDDEN",
        "catalog_mutation_without_diff": "FORBIDDEN",
        "public_ingress_default": "FORBIDDEN",
        "sensitive_action_requires_reauth": True,
        "accessibility_target": "WCAG_2_2_AA",
    }
    for key, expected in expected_c14.items():
        if c14.get(key) != expected:
            errors.append(f"C14 invariant failed: {key}")

    c15 = decisions["C15"].get("locks", {})
    expected_c15 = {
        "historical_qualified": False,
        "shadow_qualified": False,
        "paper_qualified": False,
        "canary_authorized": False,
        "live_trading_enabled": False,
        "autonomous_mode_enabled": False,
        "stage_skip": "FORBIDDEN",
        "elapsed_time_only_promotion": "FORBIDDEN",
        "pnl_only_promotion": "FORBIDDEN",
        "replay_shadow_paper_remain_on": True,
        "automatic_reversion_required": True,
        "human_approval_initially_required": True,
        "incident_recovery_auto_resume": "FORBIDDEN",
        "model_or_agent_self_promotion": "FORBIDDEN",
        "canary_without_independent_kill_switch": "FORBIDDEN",
    }
    for key, expected in expected_c15.items():
        if c15.get(key) != expected:
            errors.append(f"C15 invariant failed: {key}")

    return {
        "ok": not errors,
        "errors": errors,
        "phases": ["C13", "C14", "C15"],
        "requirement_count": sum(len(ids) for ids in REQUIRED.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_c13_c15_design(Path(args.root))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
