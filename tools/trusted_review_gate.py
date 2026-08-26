#!/usr/bin/env python3
"""Exact-SHA review gate used by the protected-base workflow.

The default mode verifies a GitHub-carried, exact-base/head/tree GPT-5.6 Sol
blind review.  It does not confuse a second GitHub account with intellectual
independence.  Callers may opt into the stricter external-identity mode for
explicitly designated risk classes; that mode remains fail closed and requires
a distinct allowlisted GitHub reviewer with an APPROVED review.

This file is intentionally self-contained.  The trusted workflow checks out
the protected base SHA before executing it, so a pull request cannot replace
the gate implementation it is asking GitHub to satisfy.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from typing import Any


TRUSTED_REVIEWERS_ENV = "MARKETOS_TRUSTED_REVIEWERS"
OWNER_LOGIN = "leon36000"
ALLOWED_VERDICTS = {"APPROVE", "APPROVE_WITH_NONBLOCKING_FINDINGS"}
ORDINARY_REVIEW_STATES = {"COMMENTED", "APPROVED"}
MAX_REVIEW_PAGES = 20


def _trusted_reviewers() -> set[str]:
    raw = os.environ.get(TRUSTED_REVIEWERS_ENV, "")
    return {login.strip() for login in raw.split(",") if login.strip()}


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MarketOS-trusted-review-gate",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read(4 * 1024 * 1024))


def _fetch_review_page(
    repository: str,
    pull_request: int,
    page: int,
) -> list[dict[str, Any]]:
    payload = _fetch_json(
        f"https://api.github.com/repos/{repository}/pulls/{pull_request}/reviews"
        f"?per_page=100&page={page}"
    )
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("GITHUB_REVIEWS_ROOT_MUST_BE_LIST_OF_OBJECTS")
    return payload


def _fetch_reviews(repository: str, pull_request: int) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for page in range(1, MAX_REVIEW_PAGES + 1):
        current_page = _fetch_review_page(repository, pull_request, page)
        reviews.extend(current_page)
        if len(current_page) < 100:
            return reviews
    raise ValueError("GITHUB_REVIEWS_PAGINATION_LIMIT")


def _fetch_tree(repository: str, commit_sha: str) -> str:
    payload = _fetch_json(f"https://api.github.com/repos/{repository}/commits/{commit_sha}")
    if not isinstance(payload, dict):
        raise ValueError("GITHUB_COMMIT_ROOT_MUST_BE_OBJECT")
    tree = payload.get("commit", {}).get("tree", {})
    tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not isinstance(tree_sha, str) or not tree_sha:
        raise ValueError("GITHUB_COMMIT_TREE_UNAVAILABLE")
    return tree_sha


def _marker(body: object, key: str) -> str | None:
    if not isinstance(body, str):
        return None
    prefix = f"{key}="
    for line in body.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _canonical_findings(findings: object) -> str:
    return json.dumps(findings, sort_keys=True, separators=(",", ":"))


def _findings_are_nonblocking(findings: object) -> bool:
    if not isinstance(findings, list):
        return False
    for finding in findings:
        if not isinstance(finding, dict):
            return False
        if finding.get("severity") in {"BLOCKER", "HIGH"} or finding.get("blocking") is True:
            return False
        if not isinstance(finding.get("summary"), str) or not finding["summary"].strip():
            return False
    return True


def _reviewer_is_authorized(
    *,
    reviewer_login: str,
    review_state: object,
    pr_author: str,
    trusted_reviewers: set[str],
    external_identity_required: bool,
) -> bool:
    if external_identity_required:
        return (
            reviewer_login not in {OWNER_LOGIN, pr_author}
            and reviewer_login in trusted_reviewers
            and review_state == "APPROVED"
        )
    return review_state in ORDINARY_REVIEW_STATES


def _review_is_exact(
    review: dict[str, Any],
    *,
    repository: str,
    base_sha: str,
    head_sha: str,
    tree_sha: str,
    pr_author: str,
    trusted_reviewers: set[str],
    external_identity_required: bool = False,
) -> bool:
    user = review.get("user")
    reviewer_login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(reviewer_login, str) or not reviewer_login.strip():
        return False
    if not _reviewer_is_authorized(
        reviewer_login=reviewer_login,
        review_state=review.get("state"),
        pr_author=pr_author,
        trusted_reviewers=trusted_reviewers,
        external_identity_required=external_identity_required,
    ):
        return False
    if review.get("commit_id") != head_sha:
        return False
    body = review.get("body")
    verdict = _marker(body, "MARKETOS_REVIEW_VERDICT")
    if verdict not in ALLOWED_VERDICTS:
        return False
    findings_text = _marker(body, "MARKETOS_REVIEW_FINDINGS_JSON")
    try:
        findings = json.loads(findings_text) if findings_text is not None else None
    except json.JSONDecodeError:
        return False
    if not isinstance(findings, list):
        return False
    if verdict == "APPROVE" and findings:
        return False
    if verdict == "APPROVE_WITH_NONBLOCKING_FINDINGS" and (
        not findings or not _findings_are_nonblocking(findings)
    ):
        return False
    expected = {
        "MARKETOS_REVIEW_REPOSITORY": repository,
        "MARKETOS_REVIEW_BASE_SHA": base_sha,
        "MARKETOS_REVIEW_HEAD_SHA": head_sha,
        "MARKETOS_REVIEW_TREE_SHA": tree_sha,
        "MARKETOS_REVIEW_VERDICT": verdict,
        "MARKETOS_REVIEW_MODEL": "GPT-5.6 Sol",
        "MARKETOS_REVIEW_CONTEXT": "independent_blind",
        "MARKETOS_REVIEW_FINDINGS_JSON": _canonical_findings(findings),
    }
    return all(_marker(body, key) == value for key, value in expected.items())


def _review_sort_key(review: dict[str, Any]) -> tuple[int, str, int]:
    submitted_at = review.get("submitted_at")
    timestamp = submitted_at.strip() if isinstance(submitted_at, str) else ""
    review_id = review.get("id")
    numeric_id = review_id if isinstance(review_id, int) else -1
    return (1 if timestamp else 0, timestamp, numeric_id)


def _has_latest_exact_review(
    reviews: list[dict[str, Any]],
    *,
    repository: str,
    base_sha: str,
    head_sha: str,
    tree_sha: str,
    pr_author: str,
    trusted_reviewers: set[str],
    external_identity_required: bool = False,
) -> bool:
    latest_by_reviewer: dict[str, dict[str, Any]] = {}
    for review in sorted(reviews, key=_review_sort_key):
        user = review.get("user")
        reviewer_login = user.get("login") if isinstance(user, dict) else None
        if isinstance(reviewer_login, str) and reviewer_login.strip():
            latest_by_reviewer[reviewer_login] = review
    return any(
        _review_is_exact(
            review,
            repository=repository,
            base_sha=base_sha,
            head_sha=head_sha,
            tree_sha=tree_sha,
            pr_author=pr_author,
            trusted_reviewers=trusted_reviewers,
            external_identity_required=external_identity_required,
        )
        for review in latest_by_reviewer.values()
    )


def verify_trusted_review_gate(
    *,
    repository: str,
    pull_request: int,
    base_sha: str,
    head_sha: str,
    pr_author: str,
    external_identity_required: bool = False,
) -> dict[str, object]:
    review_mode = (
        "EXTERNAL_EXACT_SHA" if external_identity_required else "SOL_EXACT_SHA"
    )
    if not isinstance(pr_author, str) or not pr_author.strip():
        return {"ok": False, "errors": ["PR_AUTHOR_INVALID"], "review_mode": review_mode}
    trusted_reviewers = _trusted_reviewers()
    if external_identity_required and not trusted_reviewers:
        return {
            "ok": False,
            "errors": ["TRUSTED_REVIEWER_ALLOWLIST_EMPTY"],
            "review_mode": review_mode,
        }
    try:
        tree_sha = _fetch_tree(repository, head_sha)
        reviews = _fetch_reviews(repository, pull_request)
        accepted = _has_latest_exact_review(
            reviews,
            repository=repository,
            base_sha=base_sha,
            head_sha=head_sha,
            tree_sha=tree_sha,
            pr_author=pr_author,
            trusted_reviewers=trusted_reviewers,
            external_identity_required=external_identity_required,
        )
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "errors": [f"TRUSTED_REVIEW_GATE_FAILED:{type(exc).__name__}"],
            "review_mode": review_mode,
        }
    if not accepted:
        error = (
            "NO_TRUSTED_EXACT_HEAD_APPROVAL"
            if external_identity_required
            else "NO_SOL_EXACT_HEAD_REVIEW"
        )
        return {"ok": False, "errors": [error], "review_mode": review_mode}
    return {
        "ok": True,
        "errors": [],
        "head_sha": head_sha,
        "tree_sha": tree_sha,
        "review_mode": review_mode,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--pr-author", required=True)
    parser.add_argument("--external-identity-required", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_trusted_review_gate(
        repository=args.repository,
        pull_request=args.pull_request,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        pr_author=args.pr_author,
        external_identity_required=args.external_identity_required,
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
