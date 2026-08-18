#!/usr/bin/env python3
"""Fail-closed verifier for PR14 -> PR20 architecture reconciliation.

This verifier deliberately distinguishes target architecture, verified partial slices,
and completed implementation. It never queries external services at runtime; exact
GitHub identities and CI receipts are pinned in the reconciliation artifact and the
artifact is validated for internal consistency against repository state.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


MATRIX_PATH = Path("planning/architecture/PR14_PR20_RECONCILIATION.json")
STATE_PATH = Path("authority/CURRENT_STATE.json")
REQUIREMENTS_PATH = Path("requirements/REQUIREMENT_CROSSWALK.csv")

EXPECTED_PR14_HEAD = "bd3bf2823d6e731ece5ed8d66570d196be42b560"
EXPECTED_PR20_HEAD = "b05dd6004f60cc20b76c2c5c86c3ba6046401180"
EXPECTED_PR20_BASE = "ea851564a2a5781cd3627d0dd5eb9ca857001095"
EXPECTED_SLICE_HEADS = {
    15: "fab4c16c048e3216093a43af0c42f5f0c9562c33",
    16: "9b6f9d94de82963a62e07a6183d63cf1a5dea33a",
    17: "e602c17e22caa12bf358743c47a38e90cdaeb8a9",
    18: "ffe23f955770f68bf897f94c7a506dfeb27c09b6",
    19: "ea851564a2a5781cd3627d0dd5eb9ca857001095",
    20: "b05dd6004f60cc20b76c2c5c86c3ba6046401180",
}
EXPECTED_PR14_RUNS = {
    (31761607472, "validate", "failure"),
    (31761607461, "validate-c16", "failure"),
}
EXPECTED_PR20_RUNS = {
    (32189100569, "validate", "success"),
    (32189100686, "implementation-foundation", "success"),
    (32189100652, "execution-calibration", "success"),
}
EXPECTED_NODE_IDS = [
    *[f"{index:02d}" for index in range(41)],
    *[f"PC{index}" for index in range(8)],
]
POLICY_BLOCKED_NODES = {"37", "38", "39"}
REQUIRED_GAPS = {
    "C13_RUNTIME_CONTRACTS",
    "C14_COCKPIT_AND_OPERABILITY",
    "C15_QUALIFICATION",
    "C16_PACKAGING_AND_INTEGRATION",
    "PROOF_BINDING",
    "REQUIREMENTS_119_VS_108",
}
ALLOWED_NODE_STATUSES = {"VERIFIED_PARTIAL", "UNVERIFIED_TARGET", "POLICY_BLOCKED"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, code: str, errors: list[str]) -> None:
    if not condition:
        errors.append(code)


def _run_receipts(records: object) -> set[tuple[int, str, str]]:
    if not isinstance(records, list):
        return set()
    receipts: set[tuple[int, str, str]] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        run_id = row.get("id")
        name = row.get("name")
        conclusion = row.get("conclusion")
        if isinstance(run_id, int) and isinstance(name, str) and isinstance(conclusion, str):
            receipts.add((run_id, name, conclusion))
    return receipts


def _requirement_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ids = [str(row.get("id", "")).strip() for row in rows]
    if any(not requirement_id for requirement_id in ids):
        raise ValueError("EMPTY_REQUIREMENT_ID")
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_REQUIREMENT_ID")
    return len(ids)


def verify_architecture_reconciliation(root: Path) -> dict[str, object]:
    root = root.resolve()
    errors: list[str] = []

    matrix_file = root / MATRIX_PATH
    state_file = root / STATE_PATH
    requirements_file = root / REQUIREMENTS_PATH
    _require(matrix_file.is_file(), "MISSING_RECONCILIATION_MATRIX", errors)
    _require(state_file.is_file(), "MISSING_CURRENT_STATE", errors)
    _require(requirements_file.is_file(), "MISSING_REQUIREMENT_ORACLE", errors)
    if errors:
        return {
            "ok": False,
            "errors": errors,
            "pr14_head_sha": None,
            "pr20_base_head_sha": None,
            "pr14_merge_safe": None,
            "pr14_exact_head_ci_green": None,
            "verified_execution_slices": 0,
            "implementation_nodes_complete": 0,
            "canonical_requirements": 0,
            "memory_requirements_observed": 0,
            "stale_closure_refs_treated_as_resolved": True,
            "critical_open_gaps": [],
            "live_trading_state": None,
            "profitability_state": None,
        }

    try:
        matrix = _load_json(matrix_file)
        state = _load_json(state_file)
        canonical_requirements = _requirement_count(requirements_file)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        errors.append(f"LOAD_ERROR:{type(exc).__name__}:{exc}")
        matrix = {}
        state = {}
        canonical_requirements = 0

    sources = matrix.get("sources", {}) if isinstance(matrix, dict) else {}
    pr14 = sources.get("pr14", {}) if isinstance(sources, dict) else {}
    pr20 = sources.get("pr20", {}) if isinstance(sources, dict) else {}

    _require(matrix.get("authority") == "RECONCILIATION_EVIDENCE", "WRONG_MATRIX_AUTHORITY", errors)
    _require(pr14.get("number") == 14, "PR14_ID_MISMATCH", errors)
    _require(pr14.get("head_sha") == EXPECTED_PR14_HEAD, "PR14_HEAD_MISMATCH", errors)
    _require(pr14.get("role") == "TARGET_ARCHITECTURE_ONLY", "PR14_ROLE_ESCALATED", errors)
    _require(pr14.get("merge_safe") is False, "PR14_MERGE_SAFETY_ESCALATED", errors)
    _require(pr14.get("exact_head_ci_green") is False, "PR14_CI_FALSE_GREEN", errors)
    _require(_run_receipts(pr14.get("ci_runs")) == EXPECTED_PR14_RUNS, "PR14_FAILURE_RECEIPTS_MISMATCH", errors)
    failure_causes = pr14.get("failure_causes", [])
    _require(isinstance(failure_causes, list) and len(failure_causes) >= 4, "PR14_FAILURE_CAUSES_INCOMPLETE", errors)

    _require(pr20.get("number") == 20, "PR20_ID_MISMATCH", errors)
    _require(pr20.get("head_sha") == EXPECTED_PR20_HEAD, "PR20_HEAD_MISMATCH", errors)
    _require(pr20.get("base_sha") == EXPECTED_PR20_BASE, "PR20_BASE_MISMATCH", errors)
    _require(pr20.get("role") == "EXECUTABLE_EVIDENCE_BASE", "PR20_ROLE_MISMATCH", errors)
    _require(pr20.get("exact_head_ci_green") is True, "PR20_CI_NOT_GREEN_IN_EVIDENCE", errors)
    _require(_run_receipts(pr20.get("ci_runs")) == EXPECTED_PR20_RUNS, "PR20_RUN_RECEIPTS_MISMATCH", errors)
    _require(pr20.get("full_repository_tests") == 296, "PR20_TEST_COUNT_MISMATCH", errors)
    _require(pr20.get("canonical_requirements") == 108, "PR20_REQUIREMENT_COUNT_MISMATCH", errors)

    slices = matrix.get("execution_slices", [])
    _require(isinstance(slices, list), "EXECUTION_SLICES_NOT_LIST", errors)
    slice_prs = [row.get("pr") for row in slices if isinstance(row, dict)] if isinstance(slices, list) else []
    _require(slice_prs == [15, 16, 17, 18, 19, 20], "EXECUTION_SLICE_ORDER_OR_MEMBERSHIP_MISMATCH", errors)
    expected_by_node: dict[str, set[int]] = {}
    for row in slices if isinstance(slices, list) else []:
        if not isinstance(row, dict):
            errors.append("INVALID_EXECUTION_SLICE_RECORD")
            continue
        pr = row.get("pr")
        expected_head = EXPECTED_SLICE_HEADS.get(pr)
        _require(expected_head is not None and row.get("head_sha") == expected_head, f"SLICE_{pr}_HEAD_MISMATCH", errors)
        _require(row.get("coverage") == "VERIFIED_PARTIAL", f"SLICE_{pr}_COVERAGE_ESCALATED", errors)
        _require(row.get("target_overlap_only") is True, f"SLICE_{pr}_TARGET_OVERLAP_RULE_MISSING", errors)
        ci_runs = row.get("ci_runs")
        _require(isinstance(ci_runs, list) and ci_runs and all(isinstance(run, int) and run > 0 for run in ci_runs), f"SLICE_{pr}_CI_RECEIPTS_MISSING", errors)
        for node_id in row.get("target_node_ids", []):
            _require(node_id in EXPECTED_NODE_IDS, f"SLICE_{pr}_UNKNOWN_TARGET_NODE:{node_id}", errors)
            if node_id in EXPECTED_NODE_IDS and isinstance(pr, int):
                expected_by_node.setdefault(node_id, set()).add(pr)

    requirements = matrix.get("requirements", {})
    _require(canonical_requirements == 108, "REPOSITORY_REQUIREMENT_ORACLE_NOT_108", errors)
    _require(requirements.get("canonical_repository_count") == 108, "MATRIX_CANONICAL_REQUIREMENTS_NOT_108", errors)
    _require(requirements.get("memory_observed_count") == 119, "MEMORY_REQUIREMENT_COUNT_NOT_119", errors)
    _require(requirements.get("memory_is_canonical_repository_set") is False, "MEMORY_SUPERSET_PROMOTED_TO_CANON", errors)

    target_dag = matrix.get("target_dag", {})
    _require(target_dag.get("source_pr") == 14, "TARGET_DAG_SOURCE_PR_MISMATCH", errors)
    _require(target_dag.get("source_head_sha") == EXPECTED_PR14_HEAD, "TARGET_DAG_SOURCE_SHA_MISMATCH", errors)
    _require(target_dag.get("nodes_total") == 49, "TARGET_DAG_NODE_COUNT_MISMATCH", errors)
    _require(target_dag.get("nodes_complete") == 0, "TARGET_DAG_FALSE_COMPLETION", errors)
    _require(target_dag.get("node_ids") == EXPECTED_NODE_IDS, "TARGET_DAG_NODE_IDS_MISMATCH", errors)
    _require(set(target_dag.get("policy_blocked_nodes", [])) == POLICY_BLOCKED_NODES, "POLICY_BLOCKED_NODE_SET_MISMATCH", errors)

    node_coverage = matrix.get("node_coverage", [])
    coverage_ids = [row.get("id") for row in node_coverage if isinstance(row, dict)] if isinstance(node_coverage, list) else []
    _require(coverage_ids == EXPECTED_NODE_IDS, "NODE_COVERAGE_NOT_EXACT_DAG_ORDER", errors)
    implementation_nodes_complete = 0
    for row in node_coverage if isinstance(node_coverage, list) else []:
        if not isinstance(row, dict):
            errors.append("INVALID_NODE_COVERAGE_RECORD")
            continue
        node_id = row.get("id")
        status = row.get("status")
        evidence_prs = row.get("evidence_prs")
        _require(status in ALLOWED_NODE_STATUSES, f"INVALID_NODE_STATUS:{node_id}:{status}", errors)
        if status == "COMPLETE":
            implementation_nodes_complete += 1
        expected_evidence = expected_by_node.get(str(node_id), set())
        actual_evidence = set(evidence_prs) if isinstance(evidence_prs, list) else set()
        if expected_evidence:
            _require(status == "VERIFIED_PARTIAL", f"OVERLAPPED_NODE_NOT_PARTIAL:{node_id}", errors)
            _require(actual_evidence == expected_evidence, f"NODE_EVIDENCE_MISMATCH:{node_id}", errors)
        else:
            expected_status = "POLICY_BLOCKED" if node_id in POLICY_BLOCKED_NODES else "UNVERIFIED_TARGET"
            _require(status == expected_status, f"UNMAPPED_NODE_STATUS_ESCALATED:{node_id}", errors)
            _require(not actual_evidence, f"UNMAPPED_NODE_HAS_EVIDENCE:{node_id}", errors)
    _require(implementation_nodes_complete == 0, "BROAD_NODE_FALSE_COMPLETE", errors)

    stale_claims = matrix.get("stale_claims", [])
    _require(isinstance(stale_claims, list) and len(stale_claims) >= 4, "STALE_CLAIMS_INCOMPLETE", errors)
    if isinstance(stale_claims, list):
        for row in stale_claims:
            _require(isinstance(row, dict) and row.get("accepted_as_current") is False, "STALE_CLAIM_PROMOTED", errors)

    stale_refs = matrix.get("stale_closure_refs", [])
    stale_closure_refs_treated_as_resolved = False
    _require(isinstance(stale_refs, list) and len(stale_refs) >= 2, "STALE_CLOSURE_REFS_INCOMPLETE", errors)
    if isinstance(stale_refs, list):
        for row in stale_refs:
            if not isinstance(row, dict):
                errors.append("INVALID_STALE_CLOSURE_REF")
                stale_closure_refs_treated_as_resolved = True
                continue
            rel = row.get("path")
            resolved = row.get("resolved")
            treat_as_evidence = row.get("treat_as_evidence")
            if resolved is not False or treat_as_evidence is not False:
                stale_closure_refs_treated_as_resolved = True
                errors.append(f"STALE_CLOSURE_REF_PROMOTED:{rel}")
            if not isinstance(rel, str) or not rel:
                errors.append("STALE_CLOSURE_REF_PATH_MISSING")
                stale_closure_refs_treated_as_resolved = True
            elif (root / rel).is_file():
                errors.append(f"STALE_CLOSURE_REF_NOW_EXISTS_RECONCILE_REQUIRED:{rel}")
                stale_closure_refs_treated_as_resolved = True

    critical_open_gaps = matrix.get("critical_open_gaps", [])
    _require(isinstance(critical_open_gaps, list) and set(critical_open_gaps) == REQUIRED_GAPS, "CRITICAL_OPEN_GAPS_MISMATCH", errors)

    locks = matrix.get("locks", {})
    _require(locks.get("live_trading") == "HARD_LOCKED", "MATRIX_LIVE_LOCK_WEAKENED", errors)
    _require(locks.get("profitability") == "UNPROVEN", "MATRIX_PROFITABILITY_ESCALATED", errors)
    _require(locks.get("software_implementation_complete") is False, "MATRIX_FULL_IMPLEMENTATION_FALSE_CLAIM", errors)
    _require(locks.get("strategy_edge_proven") is False, "MATRIX_STRATEGY_EDGE_ESCALATED", errors)
    _require(locks.get("broker_selected") is False, "MATRIX_BROKER_SELECTED", errors)
    _require(locks.get("production_backend_selected") is False, "MATRIX_BACKEND_SELECTED", errors)

    _require(state.get("planning_phase") == "C13", "CURRENT_STATE_PHASE_MISMATCH", errors)
    _require(state.get("planning_phase_state") == "IN_PROGRESS", "CURRENT_STATE_PHASE_STATUS_MISMATCH", errors)
    _require(state.get("audited_requirements") == 108, "CURRENT_STATE_CANONICAL_REQUIREMENT_MISMATCH", errors)
    _require(state.get("neon_requirements_total_observed") == 119, "CURRENT_STATE_MEMORY_REQUIREMENT_MISMATCH", errors)
    _require(state.get("software_implementation_state") == "PARTIAL_VERIFIED_SLICES_NOT_COMPLETE_SYSTEM", "CURRENT_STATE_IMPLEMENTATION_STATUS_STALE", errors)
    _require(state.get("software_implementation_complete") is False, "CURRENT_STATE_FALSE_IMPLEMENTATION_COMPLETE", errors)
    _require(state.get("latest_verified_execution_head_sha") == EXPECTED_PR20_HEAD, "CURRENT_STATE_EXECUTION_HEAD_MISMATCH", errors)
    _require(state.get("verified_execution_slices") == [15, 16, 17, 18, 19, 20], "CURRENT_STATE_EXECUTION_SLICE_SET_MISMATCH", errors)
    _require(state.get("pr14_current_canon_eligible") is False, "CURRENT_STATE_PR14_FALSE_PROMOTION", errors)
    _require(state.get("reconciliation_candidate_pr") == 21, "CURRENT_STATE_RECONCILIATION_PR_MISMATCH", errors)
    _require(state.get("live_trading_state") == "HARD_LOCKED", "CURRENT_STATE_LIVE_LOCK_WEAKENED", errors)
    _require(state.get("profitability_state") == "UNPROVEN", "CURRENT_STATE_PROFITABILITY_ESCALATED", errors)

    return {
        "ok": not errors,
        "errors": errors,
        "pr14_head_sha": pr14.get("head_sha"),
        "pr20_base_head_sha": pr20.get("head_sha"),
        "pr14_merge_safe": pr14.get("merge_safe"),
        "pr14_exact_head_ci_green": pr14.get("exact_head_ci_green"),
        "verified_execution_slices": len(slices) if isinstance(slices, list) else 0,
        "implementation_nodes_complete": implementation_nodes_complete,
        "canonical_requirements": canonical_requirements,
        "memory_requirements_observed": requirements.get("memory_observed_count"),
        "stale_closure_refs_treated_as_resolved": stale_closure_refs_treated_as_resolved,
        "critical_open_gaps": critical_open_gaps if isinstance(critical_open_gaps, list) else [],
        "live_trading_state": state.get("live_trading_state"),
        "profitability_state": state.get("profitability_state"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_architecture_reconciliation(Path(args.root))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
