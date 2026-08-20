#!/usr/bin/env python3
"""Verify the safe boundary between the 108-row oracle and memory observations."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


POLICY_PATH = Path("planning/architecture/REQUIREMENTS_108_119_RECONCILIATION.json")
CANONICAL_PATH = Path("requirements/REQUIREMENT_CROSSWALK.csv")
CURRENT_STATE_PATH = Path("authority/CURRENT_STATE.json")
MEMORY_STATE_PATH = Path("authority/NEON_MEMORY_STATE.json")
EXPECTED_FINDINGS = {
    "MEMORY_ROW_LEVEL_EVIDENCE_MISSING",
    "MEMORY_COUNT_CONFLICT_119_VS_111",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ids = [str(row.get("id", "")).strip() for row in rows]
    if any(not identifier for identifier in ids):
        raise ValueError("EMPTY_CANONICAL_REQUIREMENT_ID")
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_CANONICAL_REQUIREMENT_ID")
    return len(ids)


def verify_requirements_reconciliation(root: Path | str = ".") -> dict[str, object]:
    root = Path(root).resolve()
    errors: list[str] = []
    policy: dict[str, Any] = {}
    try:
        policy = _load_json(root / POLICY_PATH)
    except FileNotFoundError:
        errors.append("MISSING_REQUIREMENTS_RECONCILIATION_POLICY")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"REQUIREMENTS_POLICY_LOAD_ERROR:{type(exc).__name__}")

    try:
        canonical_count = _canonical_count(root / CANONICAL_PATH)
    except FileNotFoundError:
        canonical_count = 0
        errors.append("MISSING_CANONICAL_REQUIREMENT_ORACLE")
    except (OSError, csv.Error, ValueError) as exc:
        canonical_count = 0
        errors.append(f"CANONICAL_REQUIREMENT_ORACLE_INVALID:{exc}")

    try:
        current_state = _load_json(root / CURRENT_STATE_PATH)
    except FileNotFoundError:
        current_state = {}
        errors.append("MISSING_CURRENT_STATE")
    except (OSError, json.JSONDecodeError) as exc:
        current_state = {}
        errors.append(f"CURRENT_STATE_LOAD_ERROR:{type(exc).__name__}")

    try:
        memory_state = _load_json(root / MEMORY_STATE_PATH)
    except FileNotFoundError:
        memory_state = {}
        errors.append("MISSING_MEMORY_STATE_SNAPSHOT")
    except (OSError, json.JSONDecodeError) as exc:
        memory_state = {}
        errors.append(f"MEMORY_STATE_LOAD_ERROR:{type(exc).__name__}")

    current_count = current_state.get("neon_requirements_total_observed")
    local_count = memory_state.get("observed_counts", {}).get("requirements")
    if current_count != 119:
        errors.append("CURRENT_STATE_COUNT_NOT_119")
    if canonical_count != 108:
        errors.append("CANONICAL_COUNT_NOT_108")
    if local_count != 111:
        errors.append("LOCAL_MEMORY_SNAPSHOT_COUNT_NOT_111")

    blocking_findings = policy.get("blocking_findings", [])
    blocking_set = set(blocking_findings) if isinstance(blocking_findings, list) else set()
    if blocking_set != EXPECTED_FINDINGS:
        errors.append("BLOCKING_FINDINGS_NOT_EXPLICIT")
    if policy.get("status") != "BLOCKED_EVIDENCE_MISSING":
        errors.append("RECONCILIATION_STATUS_ESCALATED")
    if policy.get("row_level_memory_export_present") is not False:
        errors.append("ROW_LEVEL_MEMORY_EXPORT_CLAIMED_WITHOUT_EVIDENCE")
    if policy.get("reconciliation_complete") is not False:
        errors.append("RECONCILIATION_FALSE_COMPLETE")
    if policy.get("promotion_allowed") is not False:
        errors.append("MEMORY_PROMOTION_NOT_FAIL_CLOSED")

    return {
        "ok": not errors,
        "errors": errors,
        "canonical_count": canonical_count,
        "current_state_observed_count": current_count,
        "local_memory_snapshot_count": local_count,
        "reconciliation_complete": False,
        "promotion_allowed": False,
        "blocking_findings": sorted(blocking_set),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_requirements_reconciliation(args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
