#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REQUIRED_FILES = [
    "README.md", "AGENTS.md", "CLAUDE.md", "PROJECT_INSTRUCTIONS.md",
    "authority/AUTHORITY_ORDER.json", "authority/CURRENT_STATE.json",
    "authority/NEON_MEMORY_STATE.json", "authority/CLAUDE_CODE_TAKEOVER_GATE.json",
    "canon/CANON_POINTER.json", "planning/C0_1_FINAL_RECONCILIATION.md",
    "planning/PHASE_INDEX.json", "planning/phases/C1/PHASE_BRIEF.md",
    "planning/phases/C1/EXECUTION_CONTRACT.md", "requirements/REQUIREMENTS_INDEX.json",
    "memory/NEON_MEMORY_ARCHITECTURE.md",
    "amendments/MARKET-OS-HOLO-VISUAL-BRIDGE-AND-REALTIME-SOCIAL-FABRIC-AMENDMENT-v0.24.1-CANDIDATE.md",
    "research/MARKET-OS-VENDOR-COMPUTE-AND-QUANT-FINANCE-ADDENDUM-v0.24.2-CANDIDATE.md",
    "MANIFEST.json",
]

C1_REQUIRED_SECTIONS = [
    "## Objective", "## Scope", "## Out of Scope", "## Required Files",
    "## Interfaces", "## TDD Sequence", "## Verification Commands",
    "## Failure Injection", "## Exit Gate", "## Rollback",
]

IGNORED_DIR_NAMES = {".git", ".pytest_cache", "__pycache__", ".venv", "htmlcov"}
IGNORED_FILE_NAMES = {"MANIFEST.json", ".coverage", "coverage.xml", ".DS_Store"}
PYTHON_TOOL_PATTERN = re.compile(r"\bpython(?:3)?\s+(tools/[A-Za-z0-9_.\-/]+\.py)\b")


def _load_requirements(root: Path) -> tuple[list[str], int]:
    csv_path = root / "requirements" / "REQUIREMENT_CROSSWALK.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        ids = [row.get("id", "").strip() for row in rows]
        return ids, len(rows)
    index_path = root / "requirements" / "REQUIREMENTS_INDEX.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    records = data.get("requirements", [])
    ids = [str(row.get("id", "")).strip() for row in records]
    return ids, len(records)


def _is_ignored(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if path.name in IGNORED_FILE_NAMES or path.suffix == ".pyc":
        return True
    return any(part in IGNORED_DIR_NAMES for part in rel.parts)


def _execution_contract_paths(root: Path) -> list[Path]:
    paths = list((root / "execution-contracts").glob("*.md"))
    paths.extend((root / "planning" / "phases").glob("*/EXECUTION_CONTRACT.md"))
    return sorted(path for path in paths if path.is_file())


def validate_repository(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (root / rel).is_file():
            errors.append(f"missing required file: {rel}")

    state: dict[str, Any] = {}
    state_path = root / "authority" / "CURRENT_STATE.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid CURRENT_STATE.json: {exc}")
    if state.get("live_trading_state") != "HARD_LOCKED":
        errors.append("live_trading_state must remain HARD_LOCKED")
    if state.get("profitability_state") != "UNPROVEN":
        errors.append("profitability_state must remain UNPROVEN")

    phase_count = 0
    phase_data: dict[str, Any] = {}
    phase_path = root / "planning" / "PHASE_INDEX.json"
    if phase_path.is_file():
        try:
            phase_data = json.loads(phase_path.read_text(encoding="utf-8"))
            phases = phase_data.get("phases", [])
            phase_ids = [p.get("phase_id") for p in phases]
            phase_count = len(phases)
            expected = [f"C{i}" for i in range(1, 17)]
            if phase_ids != expected:
                errors.append(f"planning phases must be exactly C1-C16, got {phase_ids}")
            if phase_data.get("count") != 16:
                errors.append("PHASE_INDEX count must be 16")
            for phase in phases:
                referenced = phase.get("brief_path")
                if not referenced or not (root / referenced).is_file():
                    errors.append(f"referenced path missing for {phase.get('phase_id')}: {referenced}")
            preflight = phase_data.get("preflight", {})
            artifact = preflight.get("artifact")
            if not artifact or not (root / artifact).is_file():
                errors.append(f"referenced path missing for preflight artifact: {artifact}")
            takeover_gate = phase_data.get("takeover_gate")
            if not takeover_gate or not (root / takeover_gate).is_file():
                errors.append(f"takeover gate referenced path missing: {takeover_gate}")
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"invalid PHASE_INDEX.json: {exc}")

    requirement_count = 0
    try:
        requirement_ids, requirement_count = _load_requirements(root)
        if any(not rid for rid in requirement_ids):
            errors.append("requirements contain empty IDs")
        if len(set(requirement_ids)) != len(requirement_ids):
            errors.append("duplicate requirement IDs detected")
        if requirement_count < 108:
            errors.append(f"expected at least 108 requirements, got {requirement_count}")
        index_path = root / "requirements" / "REQUIREMENTS_INDEX.json"
        csv_path = root / "requirements" / "REQUIREMENT_CROSSWALK.csv"
        if index_path.is_file():
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
            index_records = index_data.get("requirements", [])
            index_ids = [str(row.get("id", "")).strip() for row in index_records]
            if len(set(index_ids)) != len(index_ids):
                errors.append("duplicate requirement IDs detected in compact index")
            if index_data.get("count") != len(index_records):
                errors.append("compact requirement index count does not match its records")
            if requirement_count != len(index_records):
                errors.append("CSV and compact requirement index counts diverge")
            if csv_path.is_file():
                csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                if index_data.get("source_csv_sha256") != csv_sha:
                    errors.append("compact requirement index source_csv_sha256 diverges from CSV")
    except (FileNotFoundError, json.JSONDecodeError, csv.Error, TypeError) as exc:
        errors.append(f"could not load requirements: {exc}")

    contract_path = root / "planning" / "phases" / "C1" / "EXECUTION_CONTRACT.md"
    if contract_path.is_file():
        contract = contract_path.read_text(encoding="utf-8")
        for section in C1_REQUIRED_SECTIONS:
            if section not in contract:
                errors.append(f"C1 contract missing section: {section}")

    execution_contract_count = len(_execution_contract_paths(root))
    declared_contract_count = phase_data.get("formal_execution_contracts_present")
    if declared_contract_count != execution_contract_count:
        errors.append("formal execution contract count diverges: "
                      f"declared={declared_contract_count}, repository={execution_contract_count}")

    takeover_path = root / "authority" / "CLAUDE_CODE_TAKEOVER_GATE.json"
    if takeover_path.is_file():
        try:
            takeover = json.loads(takeover_path.read_text(encoding="utf-8"))
            command_tools = PYTHON_TOOL_PATTERN.findall(str(takeover.get("verify_command", "")))
            if not command_tools:
                errors.append("takeover verify command must reference a Python tool")
            for tool_path in command_tools:
                if not (root / tool_path).is_file():
                    errors.append(f"takeover verify tool does not exist: {tool_path}")
            for read_path in takeover.get("must_read", []):
                if not (root / read_path).is_file():
                    errors.append(f"takeover must_read path missing: {read_path}")
            locks = takeover.get("locks", {})
            if locks.get("live_trading") != "HARD_LOCKED":
                errors.append("takeover gate live_trading lock must remain HARD_LOCKED")
            if locks.get("profitability") != "UNPROVEN":
                errors.append("takeover gate profitability must remain UNPROVEN")
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"invalid CLAUDE_CODE_TAKEOVER_GATE.json: {exc}")

    claude_path = root / "CLAUDE.md"
    if claude_path.is_file():
        commands = PYTHON_TOOL_PATTERN.findall(claude_path.read_text(encoding="utf-8"))
        if not commands:
            errors.append("CLAUDE.md must contain a Python repository bootstrap command")
        for tool_path in commands:
            if not (root / tool_path).is_file():
                errors.append(f"Claude bootstrap tool does not exist: {tool_path}")

    manifest_paths: set[str] = set()
    manifest_path = root / "MANIFEST.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest_data.get("files", []):
                rel, expected, expected_bytes = entry.get("path"), entry.get("sha256"), entry.get("bytes")
                if not rel or not expected or not isinstance(expected_bytes, int):
                    errors.append("manifest contains an incomplete entry")
                    continue
                rel_path = Path(rel)
                if rel_path.is_absolute() or ".." in rel_path.parts:
                    errors.append(f"unsafe manifest path: {rel}")
                    continue
                if rel in manifest_paths:
                    errors.append(f"duplicate manifest path: {rel}")
                    continue
                manifest_paths.add(rel)
                candidate = root / rel
                if not candidate.is_file():
                    errors.append(f"manifest file missing: {rel}")
                    continue
                content = candidate.read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    errors.append(f"manifest hash mismatch: {rel}")
                if len(content) != expected_bytes:
                    errors.append(f"manifest byte count mismatch: {rel} expected={expected_bytes} actual={len(content)}")
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"invalid MANIFEST.json: {exc}")

    actual_paths: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or _is_ignored(path, root):
            continue
        actual_paths.add(path.relative_to(root).as_posix())
    for rel in sorted(actual_paths - manifest_paths):
        errors.append(f"unmanifested file: {rel}")

    forbidden_suffixes = {".pem", ".key"}
    for path in root.rglob("*"):
        if not path.is_file() or _is_ignored(path, root):
            continue
        if path.name == ".env" or path.suffix.lower() in forbidden_suffixes:
            errors.append(f"forbidden secret-like file: {path.relative_to(root)}")

    return {
        "ok": not errors,
        "errors": errors,
        "requirements_count": requirement_count,
        "planning_phase_count": phase_count,
        "execution_contract_count": execution_contract_count,
        "manifested_file_count": len(manifest_paths),
        "live_trading_state": state.get("live_trading_state"),
        "profitability_state": state.get("profitability_state"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_repository(Path(args.root))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
