#!/usr/bin/env python3
"""Fail-closed proof policy verifier for exact repository evidence.

The verifier does not query GitHub and never promotes a claim by inference. It
checks that the local reconciliation artifact, current state, source authority
paths and safety locks agree with the versioned proof policy. A failed or
unresolved check makes the complete report fail.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.verify_architecture_reconciliation import verify_architecture_reconciliation
except ModuleNotFoundError:  # Direct ``python tools/verify_proof_engine.py`` execution.
    from verify_architecture_reconciliation import verify_architecture_reconciliation

try:
    from tools.verify_requirements_reconciliation import verify_requirements_reconciliation
except ModuleNotFoundError:  # Direct ``python tools/verify_proof_engine.py`` execution.
    from verify_requirements_reconciliation import verify_requirements_reconciliation

try:
    from tools.verify_proof_binding import verify_proof_binding
except ModuleNotFoundError:  # Direct ``python tools/verify_proof_engine.py`` execution.
    from verify_proof_binding import verify_proof_binding

try:
    from tools.validate_repository import validate_repository
except ModuleNotFoundError:  # Direct ``python tools/verify_proof_engine.py`` execution.
    from validate_repository import validate_repository


POLICY_PATH = Path("planning/architecture/PROOF_ENGINE_POLICY.json")
REQUIRED_CHECKS = (
    "POLICY_FLAGS",
    "SOURCE_AUTHORITY_PATHS",
    "MANIFEST_INTEGRITY",
    "RECONCILIATION_EVIDENCE",
    "CURRENT_STATE_BINDING",
    "CANONICAL_REQUIREMENT_ORACLE",
    "MEMORY_SUPERSET_BOUNDARY",
    "IMPLEMENTATION_COMPLETION_BOUNDARY",
    "LIVE_TRADING_LOCK",
    "PROFITABILITY_LOCK",
    "PROMOTION_FAIL_CLOSED",
    "APPEND_ONLY_LEDGER",
    "EXACT_SHA_BINDING",
    "PROOF_BINDING",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _result(
    *,
    errors: list[str],
    checks: dict[str, bool],
    root: Path,
) -> dict[str, object]:
    checks_passed = sum(1 for value in checks.values() if value)
    policy: dict[str, Any] = {}
    policy_path = root / POLICY_PATH
    if policy_path.is_file():
        try:
            policy = _load_json(policy_path)
        except (OSError, json.JSONDecodeError):
            pass
    promotion_rules = policy.get("promotion_rules", {})
    required_state = policy.get("required_state", {})
    return {
        "ok": not errors and checks_passed == len(REQUIRED_CHECKS),
        "errors": errors,
        "checks": checks,
        "checks_total": len(REQUIRED_CHECKS),
        "checks_passed": checks_passed,
        "exact_sha_binding_required": policy.get("exact_sha_binding_required") is True,
        "artifact_resolution_required": policy.get("artifact_resolution_required") is True,
        "source_authority_required": policy.get("source_authority_required") is True,
        "append_only_ledger": policy.get("append_only_ledger") is True,
        "stale_or_missing_reference_promotable": promotion_rules.get(
            "stale_or_missing_reference_promotable"
        ) is True,
        "failed_or_mismatched_ci_promotable": promotion_rules.get(
            "failed_or_mismatched_ci_promotable"
        ) is True,
        "proof_engine_can_unlock_live_trading": promotion_rules.get(
            "proof_engine_can_unlock_live_trading"
        ) is True,
        "proof_engine_can_prove_profitability": promotion_rules.get(
            "proof_engine_can_prove_profitability"
        ) is True,
        "live_trading_state": required_state.get("live_trading_state"),
        "profitability_state": required_state.get("profitability_state"),
    }


def verify_proof_engine(root: Path | str = ".") -> dict[str, object]:
    root = Path(root).resolve()
    errors: list[str] = []
    checks = {name: False for name in REQUIRED_CHECKS}
    policy_path = root / POLICY_PATH

    if not policy_path.is_file():
        errors.append("MISSING_PROOF_POLICY")
        return _result(errors=errors, checks=checks, root=root)

    try:
        policy = _load_json(policy_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"PROOF_POLICY_LOAD_ERROR:{type(exc).__name__}")
        return _result(errors=errors, checks=checks, root=root)

    checks["POLICY_FLAGS"] = (
        policy.get("version") == "2.0.0"
        and policy.get("authority") == "PROOF_ENGINE_POLICY"
        and policy.get("checks") == list(REQUIRED_CHECKS)
        and policy.get("exact_sha_binding_required") is True
        and policy.get("artifact_resolution_required") is True
        and policy.get("source_authority_required") is True
        and policy.get("append_only_ledger") is True
    )
    if not checks["POLICY_FLAGS"]:
        errors.append("PROOF_POLICY_FLAGS_INVALID")

    paths = policy.get("source_authority_paths")
    if not isinstance(paths, list) or not paths:
        errors.append("SOURCE_AUTHORITY_PATHS_INVALID")
    else:
        paths_ok = True
        for relative in paths:
            if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                errors.append(f"SOURCE_AUTHORITY_PATH_INVALID:{relative}")
                paths_ok = False
                continue
            if not (root / relative).is_file():
                errors.append(f"SOURCE_AUTHORITY_PATH_MISSING:{relative}")
                paths_ok = False
        checks["SOURCE_AUTHORITY_PATHS"] = paths_ok

    repository_validation = validate_repository(root)
    checks["MANIFEST_INTEGRITY"] = repository_validation.get("ok") is True
    if not checks["MANIFEST_INTEGRITY"]:
        errors.append("MANIFEST_INTEGRITY_INVALID")

    reconciliation = verify_architecture_reconciliation(root)
    checks["RECONCILIATION_EVIDENCE"] = reconciliation.get("ok") is True
    if not checks["RECONCILIATION_EVIDENCE"]:
        errors.append("RECONCILIATION_EVIDENCE_INVALID")

    requirements_boundary = verify_requirements_reconciliation(root)
    proof_binding = verify_proof_binding(root)
    checks["PROOF_BINDING"] = proof_binding.get("ok") is True
    if not checks["PROOF_BINDING"]:
        errors.append("PROOF_BINDING_INVALID")

    try:
        state = _load_json(root / "authority/CURRENT_STATE.json")
    except (OSError, json.JSONDecodeError) as exc:
        state = {}
        errors.append(f"CURRENT_STATE_LOAD_ERROR:{type(exc).__name__}")

    required_state = policy.get("required_state", {})
    checks["CURRENT_STATE_BINDING"] = (
        state.get("planning_phase") == "C13"
        and state.get("planning_phase_state") == "IN_PROGRESS"
        and state.get("reconciliation_candidate_pr") == 21
        and state.get("live_trading_state") == required_state.get("live_trading_state")
        and state.get("profitability_state") == required_state.get("profitability_state")
    )
    if not checks["CURRENT_STATE_BINDING"]:
        errors.append("CURRENT_STATE_BINDING_INVALID")

    checks["CANONICAL_REQUIREMENT_ORACLE"] = (
        reconciliation.get("canonical_requirements") == required_state.get("canonical_requirements") == 108
    )
    if not checks["CANONICAL_REQUIREMENT_ORACLE"]:
        errors.append("CANONICAL_REQUIREMENT_ORACLE_INVALID")

    checks["MEMORY_SUPERSET_BOUNDARY"] = (
        requirements_boundary.get("ok") is True
        and requirements_boundary.get("reconciliation_complete") is False
        and requirements_boundary.get("promotion_allowed") is False
        and reconciliation.get("memory_requirements_observed") == required_state.get("memory_requirements_observed") == 119
    )
    if not checks["MEMORY_SUPERSET_BOUNDARY"]:
        errors.append("REQUIREMENTS_RECONCILIATION_BOUNDARY_INVALID")

    checks["IMPLEMENTATION_COMPLETION_BOUNDARY"] = (
        reconciliation.get("implementation_nodes_complete") == required_state.get("implementation_nodes_complete") == 0
    )
    if not checks["IMPLEMENTATION_COMPLETION_BOUNDARY"]:
        errors.append("IMPLEMENTATION_COMPLETION_BOUNDARY_INVALID")

    checks["LIVE_TRADING_LOCK"] = (
        state.get("live_trading_state") == "HARD_LOCKED"
        and required_state.get("live_trading_state") == "HARD_LOCKED"
    )
    if not checks["LIVE_TRADING_LOCK"]:
        errors.append("LIVE_TRADING_LOCK_WEAKENED")

    checks["PROFITABILITY_LOCK"] = (
        state.get("profitability_state") == "UNPROVEN"
        and required_state.get("profitability_state") == "UNPROVEN"
    )
    if not checks["PROFITABILITY_LOCK"]:
        errors.append("PROFITABILITY_LOCK_WEAKENED")

    promotion_rules = policy.get("promotion_rules", {})
    checks["PROMOTION_FAIL_CLOSED"] = all(
        promotion_rules.get(name) is False
        for name in (
            "stale_or_missing_reference_promotable",
            "failed_or_mismatched_ci_promotable",
            "proof_engine_can_unlock_live_trading",
            "proof_engine_can_prove_profitability",
        )
    )
    if not checks["PROMOTION_FAIL_CLOSED"]:
        errors.append("PROMOTION_RULES_NOT_FAIL_CLOSED")

    checks["APPEND_ONLY_LEDGER"] = policy.get("append_only_ledger") is True
    if not checks["APPEND_ONLY_LEDGER"]:
        errors.append("APPEND_ONLY_LEDGER_DISABLED")

    checks["EXACT_SHA_BINDING"] = (
        policy.get("exact_sha_binding_required") is True
        and reconciliation.get("pr14_head_sha") == "bd3bf2823d6e731ece5ed8d66570d196be42b560"
        and reconciliation.get("pr20_base_head_sha") == "b05dd6004f60cc20b76c2c5c86c3ba6046401180"
    )
    if not checks["EXACT_SHA_BINDING"]:
        errors.append("EXACT_SHA_BINDING_INVALID")

    return _result(errors=errors, checks=checks, root=root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_proof_engine(args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
