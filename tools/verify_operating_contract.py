#!/usr/bin/env python3
"""Consume and verify the MarketOS agent operating contract.

The structural policy is checked on every repository validation.  A review
receipt is optional for ordinary validation, but the merge gate is only true
when an explicitly supplied receipt binds the independent review to the
expected base, current HEAD and current tree.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


POLICY_PATH = Path("authority/OPERATING_POLICY.json")
STATE_PATH = Path("authority/CURRENT_STATE.json")
SURFACES = ("AGENTS.md", "CLAUDE.md", "PROJECT_INSTRUCTIONS.md")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
TREE_RE = re.compile(r"^[0-9a-f]{40}$")
MARKER_RE = re.compile(r"(?m)^([A-Z][A-Z0-9_]*)=([^\n]+)$")

EXPECTED_MARKERS = {
    "LUNA_PARALLEL_LIMIT": "2",
    "SOL_BLIND_REVIEW_REQUIRED": "true",
    "FULL_SUITE_BEFORE_EVERY_ACTION": "false",
    "NO_STUBS": "true",
    "MERGE_REQUIRES_EXACT_SHA_REVIEW": "true",
}
EXPECTED_POLICY = {
    "version": "1.0.0",
    "policy_id": "MARKETOS_OPERATING_CONTRACT",
    "repository": "leon36000/MarketOS-",
    "instruction_surfaces": list(SURFACES),
    "required_markers": EXPECTED_MARKERS,
    "review": {
        "required": True,
        "context": "independent_blind",
        "allowed_models": ["GPT-5.6 Sol"],
        "allowed_verdicts": [
            "APPROVE",
            "APPROVE_WITH_NONBLOCKING_FINDINGS",
        ],
        "blocking_severities": ["BLOCKER", "HIGH"],
        "merge_requires_bound_receipt": True,
    },
    "locks": {
        "live_trading_state": "HARD_LOCKED",
        "profitability_state": "UNPROVEN",
        "promotion_allowed": False,
    },
}

_CONTRADICTION_PATTERNS = (
    (
        "LUNA_PARALLEL_LIMIT",
        re.compile(
            r"(?is)\b(?:three|3|more than two|unlimited)\b"
            r".{0,60}\bLuna\b.{0,60}\b(?:sub.?agents?|workers?)\b"
        ),
    ),
    (
        "SOL_BLIND_REVIEW_REQUIRED",
        re.compile(
            r"(?is)\bmerge(?:s|d)?\b.{0,60}\bwithout\b"
            r".{0,60}\b(?:Sol|independent\s+review|exact[- ]SHA)\b"
        ),
    ),
    (
        "LIVE_TRADING_LOCK",
        re.compile(
            r"(?is)\blive[_ ]trading(?:[_ ]state)?\s*[:=]\s*"
            r"(?:ENABLED|UNLOCKED|LIVE|READY)\b"
        ),
    ),
    (
        "PROFITABILITY_LOCK",
        re.compile(r"(?is)\bprofitability(?:[_ ]state)?\s*[:=]\s*PROVEN\b"),
    ),
)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_MUST_BE_OBJECT")
    return value


def _sha_is_valid(value: object) -> bool:
    return isinstance(value, str) and SHA1_RE.fullmatch(value) is not None


def _run_git(root: Path, args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return 1, ""
    return result.returncode, result.stdout.strip()


def _git_value(root: Path, *args: str) -> str | None:
    returncode, output = _run_git(root, list(args))
    return output if returncode == 0 and output else None


def _git_reachable_commits(root: Path) -> set[str] | None:
    returncode, output = _run_git(root, ["rev-list", "--all"])
    if returncode != 0:
        return None
    return {line for line in output.splitlines() if _sha_is_valid(line)}


def _policy_matches(policy: dict[str, Any], errors: list[str]) -> None:
    if policy != EXPECTED_POLICY:
        errors.append("OPERATING_POLICY_IDENTITY_OR_RULES_INVALID")


def _surface_errors(root: Path, policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for relative in SURFACES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f"OPERATING_SURFACE_MISSING_OR_SYMLINK:{relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"OPERATING_SURFACE_READ_ERROR:{relative}:{type(exc).__name__}")
            continue
        marker_matches = MARKER_RE.findall(text)
        marker_counts: dict[str, int] = {}
        observed: dict[str, str] = {}
        for key, value in marker_matches:
            marker_counts[key] = marker_counts.get(key, 0) + 1
            observed[key] = value.strip()
        for key, expected in EXPECTED_MARKERS.items():
            if marker_counts.get(key) != 1 or observed.get(key) != expected:
                errors.append(f"POLICY_MARKER_MISMATCH:{relative}:{key}")
        for rule_name, pattern in _CONTRADICTION_PATTERNS:
            if pattern.search(text):
                errors.append(f"POLICY_SEMANTIC_CONTRADICTION:{relative}:{rule_name}")
    if policy.get("instruction_surfaces") != list(SURFACES):
        errors.append("POLICY_SURFACE_SET_INVALID")
    return errors


def _review_errors(
    *,
    root: Path,
    policy: dict[str, Any],
    review_receipt: Path | None,
    expected_base_sha: str | None,
) -> tuple[list[str], bool]:
    if review_receipt is None:
        return [], False
    errors: list[str] = []
    review_policy = policy.get("review", {})
    try:
        receipt = _load_object(review_receipt)
    except FileNotFoundError:
        return ["REVIEW_RECEIPT_MISSING"], False
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"REVIEW_RECEIPT_INVALID:{type(exc).__name__}"], False

    if receipt.get("repository") != EXPECTED_POLICY["repository"]:
        errors.append("REVIEW_REPOSITORY_MISMATCH")
    if receipt.get("review_context") != review_policy.get("context"):
        errors.append("REVIEW_CONTEXT_INVALID")
    if receipt.get("reviewer_model") not in review_policy.get("allowed_models", []):
        errors.append("REVIEWER_MODEL_INVALID")
    verdict = receipt.get("verdict")
    if verdict not in review_policy.get("allowed_verdicts", []):
        errors.append("REVIEW_VERDICT_INVALID")

    actual_head = _git_value(root, "rev-parse", "HEAD")
    actual_tree = _git_value(root, "rev-parse", "HEAD^{tree}")
    if not _sha_is_valid(actual_head) or not _sha_is_valid(actual_tree):
        errors.append("GIT_CURRENT_HEAD_UNAVAILABLE")
    if receipt.get("reviewed_head_sha") != actual_head:
        errors.append("REVIEW_HEAD_SHA_MISMATCH")
    if receipt.get("reviewed_tree_sha") != actual_tree:
        errors.append("REVIEW_TREE_SHA_MISMATCH")

    reviewed_base = receipt.get("reviewed_base_sha")
    if not _sha_is_valid(reviewed_base):
        errors.append("REVIEW_BASE_SHA_INVALID")
    elif expected_base_sha is None:
        errors.append("EXPECTED_BASE_SHA_REQUIRED")
    elif reviewed_base != expected_base_sha:
        errors.append("REVIEW_BASE_SHA_MISMATCH")
    else:
        reachable = _git_reachable_commits(root)
        if reachable is None or reviewed_base not in reachable:
            errors.append("REVIEW_BASE_SHA_UNREACHABLE")

    findings = receipt.get("findings")
    if not isinstance(findings, list):
        errors.append("REVIEW_FINDINGS_INVALID")
        findings = []
    blocking_severities = set(review_policy.get("blocking_severities", []))
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"REVIEW_FINDING_INVALID:{index}")
            continue
        severity = finding.get("severity")
        if severity in blocking_severities or finding.get("blocking") is True:
            errors.append("REVIEW_BLOCKING_FINDING")
        if not isinstance(finding.get("summary"), str) or not finding["summary"].strip():
            errors.append(f"REVIEW_FINDING_SUMMARY_INVALID:{index}")
    if verdict == "APPROVE" and findings:
        errors.append("REVIEW_FINDINGS_WITH_APPROVE")
    if verdict == "APPROVE_WITH_NONBLOCKING_FINDINGS" and not findings:
        errors.append("REVIEW_NONBLOCKING_VERDICT_WITHOUT_FINDINGS")
    return errors, not errors


def verify_operating_contract(
    root: Path | str = ".",
    *,
    review_receipt: Path | str | None = None,
    expected_base_sha: str | None = None,
) -> dict[str, object]:
    root = Path(root).resolve()
    errors: list[str] = []
    policy: dict[str, Any] = {}
    policy_loaded = False
    try:
        policy = _load_object(root / POLICY_PATH)
        policy_loaded = True
    except FileNotFoundError:
        errors.append("OPERATING_POLICY_MISSING")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"OPERATING_POLICY_INVALID:{type(exc).__name__}")
    if policy_loaded:
        _policy_matches(policy, errors)
        errors.extend(_surface_errors(root, policy))

    state: dict[str, Any] = {}
    try:
        state = _load_object(root / STATE_PATH)
    except FileNotFoundError:
        errors.append("CURRENT_STATE_MISSING")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"CURRENT_STATE_INVALID:{type(exc).__name__}")
    if state.get("live_trading_state") != "HARD_LOCKED":
        errors.append("LIVE_TRADING_LOCK_WEAKENED")
    if state.get("profitability_state") != "UNPROVEN":
        errors.append("PROFITABILITY_LOCK_WEAKENED")

    receipt_path = Path(review_receipt) if review_receipt is not None else None
    if receipt_path is not None:
        review_errors, review_bound = _review_errors(
            root=root,
            policy=policy,
            review_receipt=receipt_path,
            expected_base_sha=expected_base_sha,
        )
        errors.extend(review_errors)
    else:
        review_bound = False

    merge_authorized = review_bound and not errors
    return {
        "ok": not errors,
        "errors": errors,
        "policy_id": policy.get("policy_id"),
        "review_required": policy.get("review", {}).get("required") is True,
        "review_bound": review_bound and not errors,
        "merge_authorized": merge_authorized,
        "promotion_allowed": False,
        "live_trading_state": state.get("live_trading_state"),
        "profitability_state": state.get("profitability_state"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--review-receipt")
    parser.add_argument("--expected-base-sha")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_operating_contract(
        args.root,
        review_receipt=args.review_receipt,
        expected_base_sha=args.expected_base_sha,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
