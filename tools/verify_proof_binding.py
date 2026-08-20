#!/usr/bin/env python3
"""Verify exact, fail-closed bindings for the recorded MarketOS evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


BINDING_PATH = Path("planning/architecture/PROOF_BINDING.json")
MATRIX_PATH = Path("planning/architecture/PR14_PR20_RECONCILIATION.json")
STATE_PATH = Path("authority/CURRENT_STATE.json")
EXPECTED_ARTIFACTS = [
    "planning/architecture/PR14_PR20_RECONCILIATION.json",
    "authority/CURRENT_STATE.json",
    "requirements/REQUIREMENT_CROSSWALK.csv",
]
EXPECTED_PRS = list(range(14, 21))
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in value


def _run_ids(records: object) -> list[int] | None:
    if not isinstance(records, list) or any(not isinstance(value, int) or value <= 0 for value in records):
        return None
    return list(records)


def _report(
    *,
    errors: list[str],
    bindings_checked: int,
    artifact_bindings_checked: int,
) -> dict[str, object]:
    return {
        "ok": not errors and bindings_checked == len(EXPECTED_PRS) and artifact_bindings_checked == len(EXPECTED_ARTIFACTS),
        "errors": errors,
        "bindings_checked": bindings_checked,
        "artifact_bindings_checked": artifact_bindings_checked,
        "append_only": True,
        "promotion_allowed": False,
    }


def verify_proof_binding(root: Path | str = ".") -> dict[str, object]:
    root = Path(root).resolve()
    errors: list[str] = []
    binding_path = root / BINDING_PATH
    if not binding_path.is_file():
        return _report(errors=["MISSING_PROOF_BINDING"], bindings_checked=0, artifact_bindings_checked=0)
    try:
        binding = _load_json(binding_path)
    except (OSError, json.JSONDecodeError) as exc:
        return _report(
            errors=[f"PROOF_BINDING_LOAD_ERROR:{type(exc).__name__}"],
            bindings_checked=0,
            artifact_bindings_checked=0,
        )

    if binding.get("version") != "1.0.0" or binding.get("authority") != "PROOF_BINDING":
        errors.append("PROOF_BINDING_IDENTITY_INVALID")
    if binding.get("append_only") is not True:
        errors.append("APPEND_ONLY_FLAG_DISABLED")
    if binding.get("promotion_allowed") is not False:
        errors.append("PROMOTION_FLAG_ENABLED")

    artifact_records = binding.get("artifact_bindings")
    artifact_bindings_checked = len(artifact_records) if isinstance(artifact_records, list) else 0
    if not isinstance(artifact_records, list) or [row.get("path") for row in artifact_records if isinstance(row, dict)] != EXPECTED_ARTIFACTS:
        errors.append("ARTIFACT_BINDING_SET_INVALID")
    seen_artifacts: set[str] = set()
    for row in artifact_records if isinstance(artifact_records, list) else []:
        if not isinstance(row, dict):
            errors.append("INVALID_ARTIFACT_BINDING_RECORD")
            continue
        relative = row.get("path")
        expected_hash = row.get("sha256")
        if not _safe_relative(relative):
            errors.append(f"ARTIFACT_BINDING_PATH_INVALID:{relative}")
            continue
        if relative in seen_artifacts:
            errors.append(f"DUPLICATE_ARTIFACT_BINDING:{relative}")
        seen_artifacts.add(relative)
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            errors.append(f"ARTIFACT_BINDING_SHA_INVALID:{relative}")
            continue
        artifact_path = root / relative
        if artifact_path.is_symlink():
            errors.append(f"SOURCE_ARTIFACT_SYMLINK_FORBIDDEN:{relative}")
            continue
        try:
            artifact_path.resolve().relative_to(root)
        except ValueError:
            errors.append(f"SOURCE_ARTIFACT_OUTSIDE_ROOT:{relative}")
            continue
        if not artifact_path.is_file():
            errors.append(f"SOURCE_ARTIFACT_MISSING:{relative}")
        elif _sha256(artifact_path) != expected_hash:
            errors.append(f"SOURCE_ARTIFACT_HASH_MISMATCH:{relative}")

    try:
        matrix = _load_json(root / MATRIX_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        matrix = {}
        errors.append(f"RECONCILIATION_LOAD_ERROR:{type(exc).__name__}")
    try:
        state = _load_json(root / STATE_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        state = {}
        errors.append(f"CURRENT_STATE_LOAD_ERROR:{type(exc).__name__}")

    expected_state = {
        "planning_phase": "C13",
        "planning_phase_state": "IN_PROGRESS",
        "reconciliation_candidate_pr": 21,
        "live_trading_state": "HARD_LOCKED",
        "profitability_state": "UNPROVEN",
        "software_implementation_complete": False,
    }
    state_binding = binding.get("current_state_binding")
    if state_binding != expected_state or any(state.get(key) != value for key, value in expected_state.items()):
        errors.append("CURRENT_STATE_PROOF_BINDING_MISMATCH")

    execution_records = binding.get("execution_bindings")
    bindings_checked = len(execution_records) if isinstance(execution_records, list) else 0
    actual_prs = [row.get("pr") for row in execution_records if isinstance(row, dict)] if isinstance(execution_records, list) else []
    if actual_prs != EXPECTED_PRS:
        errors.append("EXECUTION_BINDING_SET_INVALID")

    sources = matrix.get("sources", {}) if isinstance(matrix, dict) else {}
    pr14 = sources.get("pr14", {}) if isinstance(sources, dict) else {}
    pr20 = sources.get("pr20", {}) if isinstance(sources, dict) else {}
    slices = {row.get("pr"): row for row in matrix.get("execution_slices", []) if isinstance(row, dict)} if isinstance(matrix, dict) else {}

    for row in execution_records if isinstance(execution_records, list) else []:
        if not isinstance(row, dict):
            errors.append("INVALID_EXECUTION_BINDING_RECORD")
            continue
        pr = row.get("pr")
        head_sha = row.get("head_sha")
        if not isinstance(pr, int) or pr not in EXPECTED_PRS:
            errors.append(f"EXECUTION_BINDING_PR_INVALID:{pr}")
            continue
        if not isinstance(head_sha, str) or not SHA1_RE.fullmatch(head_sha):
            errors.append(f"EXECUTION_BINDING_SHA_INVALID:{pr}")
        expected = pr14 if pr == 14 else slices.get(pr, {})
        if head_sha != expected.get("head_sha"):
            errors.append(f"EXECUTION_BINDING_HEAD_MISMATCH:{pr}")
        if row.get("promotable") is not False:
            errors.append(f"EXECUTION_BINDING_PROMOTION_ENABLED:{pr}")
        if pr == 14:
            if row.get("role") != expected.get("role") or row.get("merge_safe") is not False or row.get("exact_head_ci_green") is not False:
                errors.append("EXECUTION_BINDING_PR14_STATUS_MISMATCH")
            if row.get("ci_receipts") != expected.get("ci_runs"):
                errors.append("EXECUTION_BINDING_CI_RECEIPTS_MISMATCH:14")
        else:
            if row.get("role") != expected.get("coverage") or row.get("coverage") != expected.get("coverage") or row.get("target_overlap_only") is not True:
                errors.append(f"EXECUTION_BINDING_SLICE_STATUS_MISMATCH:{pr}")
            if row.get("ci_run_ids") != _run_ids(expected.get("ci_runs")):
                errors.append(f"EXECUTION_BINDING_CI_RECEIPTS_MISMATCH:{pr}")
            if pr == 20:
                if row.get("source_role") != pr20.get("role") or row.get("ci_receipts") != pr20.get("ci_runs"):
                    errors.append("EXECUTION_BINDING_PR20_SOURCE_MISMATCH")

    return _report(
        errors=errors,
        bindings_checked=bindings_checked,
        artifact_bindings_checked=artifact_bindings_checked,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_proof_binding(args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
