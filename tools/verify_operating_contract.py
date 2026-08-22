#!/usr/bin/env python3
"""Consume and verify the MarketOS agent operating contract.

The structural policy is checked on every repository validation.  A review
receipt is optional for ordinary validation, but the merge gate is only true
when an explicitly supplied receipt binds the independent review to the
expected base, current HEAD and current tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


POLICY_PATH = Path("authority/OPERATING_POLICY.json")
STATE_PATH = Path("authority/CURRENT_STATE.json")
SURFACES = ("AGENTS.md", "CLAUDE.md", "PROJECT_INSTRUCTIONS.md")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
MARKER_RE = re.compile(r"(?m)^([A-Z][A-Z0-9_]*)=([^\n]+)$")
MAX_REVIEW_RECEIPT_BYTES = 64 * 1024
MAX_REVIEW_ARTIFACT_BYTES = 256 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

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
        "base_ref": "codex/pr14-pr20-reconciliation-proof",
        "evidence": {
            "required": True,
            "max_artifact_bytes": 262144,
            "minimum_analysis_chars": 32,
            "minimum_evidence_items": 1,
        },
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


def _policy_matches(policy: dict[str, Any], errors: list[str]) -> None:
    if policy != EXPECTED_POLICY:
        errors.append("OPERATING_POLICY_IDENTITY_OR_RULES_INVALID")


def _marker_errors(text: str, relative: str) -> list[str]:
    errors: list[str] = []
    marker_counts: dict[str, int] = {}
    observed: dict[str, str] = {}
    for key, value in MARKER_RE.findall(text):
        marker_counts[key] = marker_counts.get(key, 0) + 1
        observed[key] = value.strip()
    for key, expected in EXPECTED_MARKERS.items():
        if marker_counts.get(key) != 1 or observed.get(key) != expected:
            errors.append(f"POLICY_MARKER_MISMATCH:{relative}:{key}")
    return errors


def _semantic_errors(text: str, relative: str) -> list[str]:
    errors: list[str] = []
    for rule_name, pattern in _CONTRADICTION_PATTERNS:
        if pattern.search(text):
            errors.append(f"POLICY_SEMANTIC_CONTRADICTION:{relative}:{rule_name}")
    return errors


def _surface_file_errors(path: Path, relative: str) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return [f"OPERATING_SURFACE_MISSING_OR_SYMLINK:{relative}"]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"OPERATING_SURFACE_READ_ERROR:{relative}:{type(exc).__name__}"]
    errors = _marker_errors(text, relative)
    errors.extend(_semantic_errors(text, relative))
    return errors


def _surface_errors(root: Path, policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for relative in SURFACES:
        errors.extend(_surface_file_errors(root / relative, relative))
    if policy.get("instruction_surfaces") != list(SURFACES):
        errors.append("POLICY_SURFACE_SET_INVALID")
    return errors


def _safe_bounded_path(
    root: Path,
    raw_path: object,
    label: str,
) -> tuple[Path | None, str | None]:
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        return None, f"{label}_PATH_INVALID"
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        return None, f"{label}_SYMLINK_REJECTED"
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError:
        return None, f"{label}_MISSING"
    except ValueError:
        return None, f"{label}_OUTSIDE_ROOT"
    except (OSError, RuntimeError):
        return None, f"{label}_PATH_INVALID"
    return resolved, None


def _read_bounded_file(
    root: Path,
    raw_path: object,
    label: str,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    resolved, path_error = _safe_bounded_path(root, raw_path, label)
    if path_error is not None:
        return None, path_error
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        return None, f"{label}_ATOMIC_OPEN_UNAVAILABLE"
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow
    descriptor: int | None = None
    try:
        descriptor = os.open(resolved, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                return None, f"{label}_NOT_REGULAR_FILE"
            if metadata.st_size > max_bytes:
                return None, f"{label}_TOO_LARGE"
            content = handle.read(max_bytes + 1)
            if len(content) > max_bytes:
                return None, f"{label}_TOO_LARGE"
            return content, None
    except OSError:
        return None, f"{label}_READ_FAILED"
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_object_bytes(content: bytes) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_MUST_BE_OBJECT")
    return value


def _review_identity_errors(
    receipt: dict[str, Any],
    review_policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if receipt.get("repository") != EXPECTED_POLICY["repository"]:
        errors.append("REVIEW_REPOSITORY_MISMATCH")
    if receipt.get("review_context") != review_policy.get("context"):
        errors.append("REVIEW_CONTEXT_INVALID")
    if receipt.get("reviewer_model") not in review_policy.get("allowed_models", []):
        errors.append("REVIEWER_MODEL_INVALID")
    if receipt.get("verdict") not in review_policy.get("allowed_verdicts", []):
        errors.append("REVIEW_VERDICT_INVALID")
    return errors


def _review_sha_errors(
    root: Path,
    receipt: dict[str, Any],
    expected_base_sha: str | None,
    review_policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    actual_head = _git_value(root, "rev-parse", "HEAD")
    actual_tree = _git_value(root, "rev-parse", "HEAD^{tree}")
    if not _sha_is_valid(actual_head) or not _sha_is_valid(actual_tree):
        errors.append("GIT_CURRENT_HEAD_UNAVAILABLE")
    if receipt.get("reviewed_head_sha") != actual_head:
        errors.append("REVIEW_HEAD_SHA_MISMATCH")
    if receipt.get("reviewed_tree_sha") != actual_tree:
        errors.append("REVIEW_TREE_SHA_MISMATCH")

    base_ref = review_policy.get("base_ref")
    authoritative_base_sha: str | None = None
    if isinstance(base_ref, str) and base_ref:
        authoritative_base_sha = _git_value(
            root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"refs/remotes/origin/{base_ref}",
        )
    if not _sha_is_valid(authoritative_base_sha):
        errors.append("REVIEW_BASE_TARGET_UNAVAILABLE")

    reviewed_base = receipt.get("reviewed_base_sha")
    if not _sha_is_valid(reviewed_base):
        errors.append("REVIEW_BASE_SHA_INVALID")
    elif expected_base_sha is None:
        errors.append("EXPECTED_BASE_SHA_REQUIRED")
    elif reviewed_base != expected_base_sha:
        errors.append("REVIEW_BASE_SHA_MISMATCH")
    if _sha_is_valid(authoritative_base_sha):
        if expected_base_sha != authoritative_base_sha:
            errors.append("REVIEW_EXPECTED_BASE_SHA_MISMATCH")
        if reviewed_base != authoritative_base_sha:
            errors.append("REVIEW_BASE_TARGET_MISMATCH")
    return errors


def _review_finding_errors(
    finding: object,
    index: int,
    blocking_severities: set[str],
) -> list[str]:
    if not isinstance(finding, dict):
        return [f"REVIEW_FINDING_INVALID:{index}"]
    errors: list[str] = []
    if finding.get("severity") in blocking_severities or finding.get("blocking") is True:
        errors.append("REVIEW_BLOCKING_FINDING")
    summary = finding.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append(f"REVIEW_FINDING_SUMMARY_INVALID:{index}")
    return errors


def _review_findings_errors(
    verdict: object,
    findings: object,
    review_policy: dict[str, Any],
) -> list[str]:
    if not isinstance(findings, list):
        return ["REVIEW_FINDINGS_INVALID"]
    errors: list[str] = []
    blocking_severities = set(review_policy.get("blocking_severities", []))
    for index, finding in enumerate(findings):
        errors.extend(_review_finding_errors(finding, index, blocking_severities))
    if verdict == "APPROVE" and findings:
        errors.append("REVIEW_FINDINGS_WITH_APPROVE")
    if verdict == "APPROVE_WITH_NONBLOCKING_FINDINGS" and not findings:
        errors.append("REVIEW_NONBLOCKING_VERDICT_WITHOUT_FINDINGS")
    return errors


def _review_evidence_metadata_errors(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    review_id = receipt.get("review_id")
    if not isinstance(review_id, str) or not review_id.strip():
        errors.append("REVIEW_ID_INVALID")
    artifact_digest = receipt.get("review_artifact_sha256")
    if not isinstance(artifact_digest, str) or SHA256_RE.fullmatch(artifact_digest) is None:
        errors.append("REVIEW_ARTIFACT_DIGEST_INVALID")
    if not isinstance(receipt.get("review_artifact_path"), (str, Path)):
        errors.append("REVIEW_ARTIFACT_PATH_INVALID")
    return errors


def _artifact_binding_errors(
    receipt: dict[str, Any],
    artifact: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in (
        "review_id",
        "repository",
        "reviewer_model",
        "review_context",
        "reviewed_base_sha",
        "reviewed_head_sha",
        "reviewed_tree_sha",
        "verdict",
        "findings",
    ):
        if artifact.get(field) != receipt.get(field):
            errors.append(f"REVIEW_ARTIFACT_BINDING_MISMATCH:{field}")
    return errors


def _artifact_analysis_errors(
    artifact: dict[str, Any],
    evidence_policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    minimum_chars = evidence_policy.get("minimum_analysis_chars", 32)
    analysis = artifact.get("analysis")
    if (
        not isinstance(minimum_chars, int)
        or not isinstance(analysis, str)
        or len(analysis.strip()) < minimum_chars
    ):
        errors.append("REVIEW_ARTIFACT_ANALYSIS_INVALID")

    evidence = artifact.get("evidence")
    minimum_items = evidence_policy.get("minimum_evidence_items", 1)
    if not isinstance(evidence, list) or not isinstance(minimum_items, int):
        return errors + ["REVIEW_ARTIFACT_EVIDENCE_INVALID"]
    if len(evidence) < minimum_items:
        errors.append("REVIEW_ARTIFACT_EVIDENCE_INSUFFICIENT")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"REVIEW_ARTIFACT_EVIDENCE_ITEM_INVALID:{index}")
            continue
        if not isinstance(item.get("command"), str) or not item["command"].strip():
            errors.append(f"REVIEW_ARTIFACT_EVIDENCE_COMMAND_INVALID:{index}")
        if not isinstance(item.get("result"), str) or not item["result"].strip():
            errors.append(f"REVIEW_ARTIFACT_EVIDENCE_RESULT_INVALID:{index}")
    return errors


def _review_evidence_errors(
    root: Path,
    receipt: dict[str, Any],
    review_policy: dict[str, Any],
) -> list[str]:
    errors = _review_evidence_metadata_errors(receipt)
    artifact_path = receipt.get("review_artifact_path")
    artifact_bytes, read_error = _read_bounded_file(
        root,
        artifact_path,
        "REVIEW_ARTIFACT",
        MAX_REVIEW_ARTIFACT_BYTES,
    )
    if read_error is not None:
        return errors + [read_error]
    actual_digest = hashlib.sha256(artifact_bytes).hexdigest()
    if actual_digest != receipt.get("review_artifact_sha256"):
        return errors + ["REVIEW_ARTIFACT_DIGEST_MISMATCH"]
    try:
        artifact = _load_object_bytes(artifact_bytes)
    except (UnicodeError, ValueError) as exc:
        return errors + [f"REVIEW_ARTIFACT_INVALID:{type(exc).__name__}"]
    errors.extend(_artifact_binding_errors(receipt, artifact))
    errors.extend(_artifact_analysis_errors(artifact, review_policy.get("evidence", {})))
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
    receipt_bytes, read_error = _read_bounded_file(
        root,
        review_receipt,
        "REVIEW_RECEIPT",
        MAX_REVIEW_RECEIPT_BYTES,
    )
    if read_error is not None:
        return [read_error], False
    errors: list[str] = []
    review_policy = policy.get("review", {})
    try:
        receipt = _load_object_bytes(receipt_bytes)
    except (UnicodeError, ValueError) as exc:
        return [f"REVIEW_RECEIPT_INVALID:{type(exc).__name__}"], False

    findings = receipt.get("findings")
    errors.extend(_review_identity_errors(receipt, review_policy))
    errors.extend(_review_sha_errors(root, receipt, expected_base_sha, review_policy))
    errors.extend(_review_findings_errors(receipt.get("verdict"), findings, review_policy))
    errors.extend(_review_evidence_errors(root, receipt, review_policy))
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
    except (OSError, ValueError) as exc:
        errors.append(f"OPERATING_POLICY_INVALID:{type(exc).__name__}")
    if policy_loaded:
        _policy_matches(policy, errors)
        errors.extend(_surface_errors(root, policy))

    state: dict[str, Any] = {}
    try:
        state = _load_object(root / STATE_PATH)
    except FileNotFoundError:
        errors.append("CURRENT_STATE_MISSING")
    except (OSError, ValueError) as exc:
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
