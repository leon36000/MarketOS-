#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import deque
from pathlib import Path
from typing import Any

EXPECTED_NODE_IDS = {f"{i:02d}" for i in range(41)} | {f"PC{i}" for i in range(8)}
FINAL_REQUIREMENTS = {
    "AUD-GOV-004", "AUD-GOV-005", "AUD-GOV-006", "AUD-GOV-007", "AUD-GOV-009", "AUD-GOV-010", "AUD-GOV-011", "AUD-GOV-013", "AUD-GOV-014",
    "AUD-MKT-016", "AUD-AI-011", "AUD-CMP-019",
    "AUD-FIN-001", "AUD-FIN-003", "AUD-FIN-004", "AUD-FIN-005", "AUD-FIN-006", "AUD-FIN-007", "AUD-FIN-008",
}
CRITICAL_FILES = [
    "planning/phases/C16/C16_DECISIONS.json",
    "planning/phases/C16/C16_REQUIREMENT_CLOSURE.json",
    "planning/phases/C16/EXECUTION_CONTRACT.md",
    "implementation/IMPLEMENTATION_DAG.json",
    "docs/architecture/C16_FINAL_IMPLEMENTATION_HANDOFF.md",
    "docs/architecture/C16_BUILD_PACK_ACCEPTANCE.md",
    "docs/architecture/C16_PACKAGING_PROVENANCE.md",
    "docs/research/C16_FINAL_AUDIT.md",
    "docs/research/C16_SOURCE_LEDGER.md",
    "tools/build_claude_pack.py",
]


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


def _crosswalk_ids(root: Path, errors: list[str]) -> set[str]:
    path = root / "requirements/REQUIREMENT_CROSSWALK.csv"
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            ids = [row["id"].strip() for row in csv.DictReader(handle)]
    except Exception as exc:
        errors.append(f"could not read crosswalk: {exc}")
        return set()
    if any(not item for item in ids):
        errors.append("crosswalk contains empty requirement IDs")
    if len(ids) != len(set(ids)):
        errors.append("crosswalk contains duplicate requirement IDs")
    return set(ids)


def _acyclic(nodes: list[dict[str, Any]], errors: list[str]) -> bool:
    ids = {str(node.get("id")) for node in nodes}
    incoming = {node_id: 0 for node_id in ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for node in nodes:
        node_id = str(node.get("id"))
        dependencies = node.get("depends_on", [])
        if not isinstance(dependencies, list):
            errors.append(f"DAG dependencies must be a list: {node_id}")
            return False
        for dependency in dependencies:
            dependency = str(dependency)
            if dependency not in ids:
                errors.append(f"DAG dependency missing: {node_id} -> {dependency}")
                continue
            if dependency == node_id:
                errors.append(f"DAG self dependency: {node_id}")
            incoming[node_id] += 1
            outgoing[dependency].append(node_id)
    queue = deque(sorted(node_id for node_id, count in incoming.items() if count == 0))
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for child in outgoing[current]:
            incoming[child] -= 1
            if incoming[child] == 0:
                queue.append(child)
    if visited != len(ids):
        errors.append("implementation DAG contains a cycle")
        return False
    return True


def validate_c16_design(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    for relative in CRITICAL_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing C16 artifact: {relative}")

    decisions = _load(root / "planning/phases/C16/C16_DECISIONS.json", errors)
    closure = _load(root / "planning/phases/C16/C16_REQUIREMENT_CLOSURE.json", errors)
    dag = _load(root / "implementation/IMPLEMENTATION_DAG.json", errors)
    state = _load(root / "authority/CURRENT_STATE.json", errors)
    phase_index = _load(root / "planning/PHASE_INDEX.json", errors)

    if decisions.get("phase") != "C16":
        errors.append("C16 decision phase mismatch")
    if decisions.get("status") not in {"CANDIDATE_PENDING_VERIFICATION", "DESIGN_GATE_PASS"}:
        errors.append("C16 decision status invalid")
    locks = decisions.get("locks", {})
    expected_locks = {
        "live_trading": "HARD_LOCKED",
        "profitability": "UNPROVEN",
        "software_implementation_complete": False,
        "implementation_nodes_completed": 0,
        "provider_selected": False,
        "trading_engine_selected": False,
        "broker_selected": False,
        "strategy_edge_proven": False,
        "champion_promoted": False,
        "historical_qualified": False,
        "shadow_qualified": False,
        "paper_qualified": False,
        "canary_authorized": False,
        "live_trading_enabled": False,
        "false_done": "FORBIDDEN",
        "critical_placeholder": "FORBIDDEN",
    }
    for key, expected in expected_locks.items():
        if locks.get(key) != expected:
            errors.append(f"C16 invariant failed: {key}")

    crosswalk_ids = _crosswalk_ids(root, errors)
    covered_ids = set(closure.get("global_audit", {}).get("covered_requirement_ids", []))
    if crosswalk_ids != covered_ids:
        errors.append(f"global requirement coverage mismatch: missing={sorted(crosswalk_ids-covered_ids)}, extra={sorted(covered_ids-crosswalk_ids)}")
    if set(closure.get("requirement_ids", [])) != FINAL_REQUIREMENTS:
        errors.append("C16 final requirement set mismatch")
    for artifact in closure.get("artifacts", []):
        if not (root / artifact).is_file():
            errors.append(f"C16 closure references missing artifact: {artifact}")
    for path in closure.get("global_audit", {}).get("phase_closure_files", []):
        if not (root / path).is_file():
            errors.append(f"phase closure file missing: {path}")
    boundary = closure.get("hard_boundary", {})
    if boundary.get("software_implementation_complete") is not False or boundary.get("implementation_nodes_completed") != 0:
        errors.append("C16 hard boundary falsely claims implementation")
    if boundary.get("live_trading") != "HARD_LOCKED" or boundary.get("profitability") != "UNPROVEN":
        errors.append("C16 hard boundary weakens financial locks")

    phases = phase_index.get("phases", [])
    phase_ids = [item.get("phase_id") for item in phases]
    if phase_ids != [f"C{i}" for i in range(1, 17)]:
        errors.append("phase index must contain C1-C16 in order")
    phase_pass = sum(item.get("status") == "DESIGN_GATE_PASS" for item in phases)
    c16_structural_pass = decisions.get("status") in {"CANDIDATE_PENDING_VERIFICATION", "DESIGN_GATE_PASS"}
    design_phases_pass = phase_pass + (1 if phase_pass == 15 and c16_structural_pass else 0)
    if design_phases_pass != 16:
        errors.append(f"expected 16 design phases structurally complete, got {design_phases_pass}")

    nodes = dag.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("implementation DAG nodes must be a list")
        nodes = []
    ids = [str(node.get("id")) for node in nodes]
    if len(ids) != len(set(ids)):
        errors.append("implementation DAG contains duplicate node IDs")
    if set(ids) != EXPECTED_NODE_IDS:
        errors.append(f"implementation DAG node set mismatch: missing={sorted(EXPECTED_NODE_IDS-set(ids))}, extra={sorted(set(ids)-EXPECTED_NODE_IDS)}")
    if dag.get("node_count") != 49 or len(nodes) != 49:
        errors.append("implementation DAG must contain exactly 49 nodes")
    completed = sum(node.get("status") == "COMPLETE" for node in nodes)
    if completed:
        errors.append("implementation nodes cannot be COMPLETE in the design pack")
    for node in nodes:
        if node.get("status") != "NOT_STARTED":
            errors.append(f"implementation node must be NOT_STARTED: {node.get('id')}")
    for live_node in ("37", "38", "39"):
        match = next((node for node in nodes if node.get("id") == live_node), None)
        if not match or match.get("blocked_by_policy") is not True:
            errors.append(f"live implementation node must remain policy-blocked: {live_node}")
    _acyclic(nodes, errors)

    if state.get("live_trading_state") != "HARD_LOCKED" or state.get("profitability_state") != "UNPROVEN":
        errors.append("Current State weakens financial locks")
    if state.get("software_implementation_state") != "NOT_STARTED_AS_COMPLETE_SYSTEM":
        errors.append("Current State must not claim software completion")

    forbidden_tokens = ("TODO", "TBD", "CHANGE_ME", "dummy_secret", "example_api_key")
    for relative in (
        "planning/phases/C16/EXECUTION_CONTRACT.md",
        "docs/architecture/C16_FINAL_IMPLEMENTATION_HANDOFF.md",
        "docs/architecture/C16_BUILD_PACK_ACCEPTANCE.md",
        "docs/architecture/C16_PACKAGING_PROVENANCE.md",
    ):
        path = root / relative
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    errors.append(f"critical C16 artifact contains forbidden placeholder {token}: {relative}")

    return {
        "ok": not errors,
        "errors": errors,
        "requirements_total": len(crosswalk_ids),
        "requirements_covered": len(covered_ids & crosswalk_ids),
        "design_phases_pass": design_phases_pass,
        "implementation_nodes": len(nodes),
        "implementation_nodes_completed": completed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_c16_design(Path(args.root))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
