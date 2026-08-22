#!/usr/bin/env python3
"""Build and verify an exact-head GitHub review receipt.

This is the promotion-side adapter.  It discovers an external GitHub review,
materializes its body as a short-lived in-worktree evidence artifact, and then
delegates all binding and lock checks to ``verify_operating_contract``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

try:
    from tools.verify_operating_contract import verify_operating_contract
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_operating_contract import verify_operating_contract


def _fetch_github_reviews(repository: str, pull_request: int) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{repository}/pulls/{pull_request}/reviews"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MarketOS-review-gate",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read(4 * 1024 * 1024))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("GITHUB_REVIEWS_ROOT_MUST_BE_LIST_OF_OBJECTS")
    return payload


def _marker(body: object, key: str) -> str | None:
    if not isinstance(body, str):
        return None
    prefix = f"{key}="
    for line in body.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _select_exact_review(
    reviews: list[dict[str, Any]],
    *,
    repository: str,
    pull_request: int,
    base_sha: str,
    head_sha: str,
    tree_sha: str,
    owner_login: str,
) -> dict[str, Any]:
    for review in reversed(reviews):
        user = review.get("user")
        reviewer_login = user.get("login") if isinstance(user, dict) else None
        body = review.get("body")
        if review.get("state") != "APPROVED":
            continue
        if reviewer_login == owner_login or not isinstance(reviewer_login, str):
            continue
        if review.get("commit_id") != head_sha:
            continue
        markers = {
            "MARKETOS_REVIEW_REPOSITORY": repository,
            "MARKETOS_REVIEW_BASE_SHA": base_sha,
            "MARKETOS_REVIEW_HEAD_SHA": head_sha,
            "MARKETOS_REVIEW_TREE_SHA": tree_sha,
            "MARKETOS_REVIEW_VERDICT": "APPROVE",
            "MARKETOS_REVIEW_MODEL": "GPT-5.6 Sol",
            "MARKETOS_REVIEW_CONTEXT": "independent_blind",
        }
        if any(_marker(body, key) != expected for key, expected in markers.items()):
            continue
        if not isinstance(review.get("id"), int) or not isinstance(review.get("html_url"), str):
            continue
        return {
            "pull_request": pull_request,
            "review_id": review["id"],
            "review_url": review["html_url"],
            "reviewer_login": reviewer_login,
            "reviewer_model": "GPT-5.6 Sol",
            "review_context": "independent_blind",
            "reviewed_base_sha": base_sha,
            "reviewed_head_sha": head_sha,
            "reviewed_tree_sha": tree_sha,
            "verdict": "APPROVE",
            "findings": [],
            "repository": repository,
            "review": review,
        }
    raise ValueError("NO_EXTERNAL_EXACT_HEAD_APPROVAL")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _build_receipt(root: Path, selected: dict[str, Any], workspace: Path) -> Path:
    review = selected["review"]
    artifact = {
        key: selected[key]
        for key in (
            "review_id",
            "pull_request",
            "review_url",
            "reviewer_login",
            "repository",
            "reviewer_model",
            "review_context",
            "reviewed_base_sha",
            "reviewed_head_sha",
            "reviewed_tree_sha",
            "verdict",
            "findings",
        )
    }
    artifact.update(
        {
            "analysis": review.get("body", ""),
            "evidence": [
                {
                    "command": "GET GitHub pull-request review API",
                    "result": "External APPROVED review matched the exact commit and markers",
                }
            ],
        }
    )
    artifact_path = workspace / "artifact.json"
    receipt_path = workspace / "receipt.json"
    _write_json(artifact_path, artifact)
    artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    receipt = {key: selected[key] for key in selected if key != "review"}
    receipt.update(
        {
            "review_artifact_path": str(artifact_path.relative_to(root)),
            "review_artifact_sha256": artifact_digest,
        }
    )
    _write_json(receipt_path, receipt)
    return receipt_path


def verify_github_review(
    root: Path,
    *,
    repository: str,
    pull_request: int,
    expected_base_sha: str,
    expected_head_sha: str,
) -> dict[str, object]:
    current_head = _fetch_git_value(root, "rev-parse", "HEAD")
    current_tree = _fetch_git_value(root, "rev-parse", "HEAD^{tree}")
    if current_head != expected_head_sha:
        return {"ok": False, "errors": ["CURRENT_HEAD_EVENT_MISMATCH"]}
    if not current_tree:
        return {"ok": False, "errors": ["CURRENT_TREE_UNAVAILABLE"]}
    try:
        reviews = _fetch_github_reviews(repository, pull_request)
        selected = _select_exact_review(
            reviews,
            repository=repository,
            pull_request=pull_request,
            base_sha=expected_base_sha,
            head_sha=expected_head_sha,
            tree_sha=current_tree,
            owner_login="leon36000",
        )
        with tempfile.TemporaryDirectory(
            dir=root / "authority",
            prefix=".marketos-review-gate-",
        ) as workspace:
            receipt_path = _build_receipt(root, selected, Path(workspace))
            return verify_operating_contract(
                root,
                review_receipt=receipt_path,
                expected_base_sha=expected_base_sha,
            )
    except (OSError, ValueError) as exc:
        return {"ok": False, "errors": [f"GITHUB_REVIEW_GATE_FAILED:{type(exc).__name__}"]}


def _fetch_git_value(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_github_review(
        Path(args.root).resolve(),
        repository=args.repository,
        pull_request=args.pull_request,
        expected_base_sha=args.expected_base_sha,
        expected_head_sha=args.expected_head_sha,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report.get("merge_authorized") else "FAIL")
        for error in report.get("errors", []):
            print(f"- {error}")
    return 0 if report.get("merge_authorized") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
