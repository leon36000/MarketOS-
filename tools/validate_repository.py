#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "PROJECT_INSTRUCTIONS.md",
    "authority/AUTHORITY_ORDER.json",
    "authority/CURRENT_STATE.json",
    "authority/NEON_MEMORY_STATE.json",
    "planning/PHASE_INDEX.json",
    "planning/phases/C1/PHASE_BRIEF.md",
    "planning/phases/C1/EXECUTION_CONTRACT.md",
    "requirements/REQUIREMENTS_INDEX.json",
    "memory/NEON_MEMORY_ARCHITECTURE.md",
    "MANIFEST.json",
]

C1_REQUIRED_SECTIONS = [
    "## Objective",
    "## Scope",
    "## Out of Scope",
    "## Required Files",
    "## Interfaces",
    "## TDD Sequence",
    "## Verification Commands",
    "## Failure Injection",
    "## Exit Gate",
    "## Rollback",
]


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
    except (FileNotFoundError, json.JSONDecodeError, csv.Error, TypeError) as exc:
        errors.append(f"could not load requirements: {exc}")

    contract_path = root / "planning" / "phases" / "C1" / "EXECUTION_CONTRACT.md"
    if contract_path.is_file():
        contract = contract_path.read_text(encoding="utf-8")
        for section in C1_REQUIRED_SECTIONS:
            if section not in contract:
                errors.append(f"C1 contract missing section: {section}")

    manifest_path = root / "MANIFEST.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest_data.get("files", []):
                rel = entry.get("path")
                expected = entry.get("sha256")
                if not rel or not expected:
                    errors.append("manifest contains an incomplete entry")
                    continue
                candidate = root / rel
                if not candidate.is_file():
                    errors.append(f"manifest file missing: {rel}")
                    continue
                actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if actual != expected:
                    errors.append(f"manifest hash mismatch: {rel}")
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"invalid MANIFEST.json: {exc}")

    forbidden_suffixes = {".pem", ".key"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == ".env" or path.suffix.lower() in forbidden_suffixes:
            errors.append(f"forbidden secret-like file: {path.relative_to(root)}")

    return {
        "ok": not errors,
        "errors": errors,
        "requirements_count": requirement_count,
        "planning_phase_count": phase_count,
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
