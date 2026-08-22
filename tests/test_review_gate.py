from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.verify_operating_contract import verify_operating_contract
from tools.verify_github_review import (
    _select_exact_review,
    verify_github_review,
)


ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40


def _review(**overrides: object) -> dict[str, object]:
    review: dict[str, object] = {
        "id": 12345,
        "user": {"login": "external-sol-reviewer"},
        "state": "APPROVED",
        "commit_id": HEAD_SHA,
        "html_url": "https://github.com/leon36000/MarketOS-/pull/30#pullrequestreview-12345",
        "body": (
            "MARKETOS_REVIEW_REPOSITORY=leon36000/MarketOS-\n"
            f"MARKETOS_REVIEW_BASE_SHA={BASE_SHA}\n"
            f"MARKETOS_REVIEW_HEAD_SHA={HEAD_SHA}\n"
            f"MARKETOS_REVIEW_TREE_SHA={TREE_SHA}\n"
            "MARKETOS_REVIEW_VERDICT=APPROVE\n"
            "MARKETOS_REVIEW_MODEL=GPT-5.6 Sol\n"
            "MARKETOS_REVIEW_CONTEXT=independent_blind\n"
            "Independent review evidence."
        ),
    }
    review.update(overrides)
    return review


class ReviewGateTests(unittest.TestCase):
    def test_selector_requires_external_exact_head_review(self) -> None:
        selected = _select_exact_review(
            [_review()],
            repository="leon36000/MarketOS-",
            pull_request=30,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            tree_sha=TREE_SHA,
            owner_login="leon36000",
        )
        self.assertEqual(selected["review_id"], 12345)
        self.assertEqual(selected["reviewer_login"], "external-sol-reviewer")

    def test_selector_rejects_stale_review(self) -> None:
        with self.assertRaisesRegex(ValueError, "NO_EXTERNAL_EXACT_HEAD_APPROVAL"):
            _select_exact_review(
                [_review(commit_id="0" * 40)],
                repository="leon36000/MarketOS-",
                pull_request=30,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                owner_login="leon36000",
            )

    def test_gate_fails_when_no_external_review_exists(self) -> None:
        current_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
        with patch(
            "tools.verify_github_review._fetch_github_reviews",
            return_value=[],
        ):
            report = verify_github_review(
                ROOT,
                repository="leon36000/MarketOS-",
                pull_request=30,
                expected_base_sha=BASE_SHA,
                expected_head_sha=current_head,
            )
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(error.startswith("GITHUB_REVIEW_GATE_FAILED:") for error in report["errors"])
        )

    def test_merge_ref_rejects_review_bound_only_to_pr_head(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="marketos-merge-ref-"))
        self.addCleanup(shutil.rmtree, temp_dir, True)
        repo = temp_dir / "repo"
        shutil.copytree(
            ROOT,
            repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__"),
        )

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()

        git("init")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "MarketOS test")
        git("add", "-A")
        git("commit", "-m", "base", "--quiet")
        base = git("rev-parse", "HEAD")
        git(
            "update-ref",
            "refs/remotes/origin/codex/pr14-pr20-reconciliation-proof",
            base,
        )
        git("checkout", "-b", "feature", "--quiet")
        readme = repo / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nmerge-ref fixture\n", encoding="utf-8")
        git("add", "README.md")
        git("commit", "-m", "feature", "--quiet")
        feature_head = git("rev-parse", "HEAD")
        feature_tree = git("rev-parse", "HEAD^{tree}")
        git("checkout", "-b", "merge", base, "--quiet")
        git("merge", "--no-ff", "feature", "-m", "merge", "--quiet")
        merge_head = git("rev-parse", "HEAD")
        git("update-ref", "refs/pull/30/merge", merge_head)
        git("checkout", "--detach", "refs/pull/30/merge", "--quiet")
        self.assertEqual(git("rev-parse", "HEAD"), merge_head)

        source = _review(
            commit_id=feature_head,
            body=(
                "MARKETOS_REVIEW_REPOSITORY=leon36000/MarketOS-\n"
                f"MARKETOS_REVIEW_BASE_SHA={base}\n"
                f"MARKETOS_REVIEW_HEAD_SHA={feature_head}\n"
                f"MARKETOS_REVIEW_TREE_SHA={feature_tree}\n"
                "MARKETOS_REVIEW_VERDICT=APPROVE\n"
                "MARKETOS_REVIEW_MODEL=GPT-5.6 Sol\n"
                "MARKETOS_REVIEW_CONTEXT=independent_blind\n"
                "Independent merge-ref fixture evidence."
            ),
        )
        artifact = {
            "review_id": 12345,
            "pull_request": 30,
            "review_url": source["html_url"],
            "reviewer_login": "external-sol-reviewer",
            "repository": "leon36000/MarketOS-",
            "reviewer_model": "GPT-5.6 Sol",
            "review_context": "independent_blind",
            "reviewed_base_sha": base,
            "reviewed_head_sha": feature_head,
            "reviewed_tree_sha": feature_tree,
            "verdict": "APPROVE",
            "analysis": "Independent merge-ref fixture analysis with exact source evidence.",
            "evidence": [{"command": "git rev-parse", "result": "fixture"}],
            "findings": [],
        }
        artifact_path = repo / "authority" / "review-artifact.json"
        receipt_path = repo / "authority" / "review-receipt.json"
        artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
        receipt = dict(artifact)
        receipt["review_artifact_path"] = "authority/review-artifact.json"
        receipt["review_artifact_sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        with patch(
            "tools.verify_operating_contract._fetch_github_review",
            return_value=source,
        ):
            report = verify_operating_contract(
                repo,
                review_receipt=receipt_path,
                expected_base_sha=base,
            )
        self.assertFalse(report["ok"])
        self.assertIn("REVIEW_HEAD_SHA_MISMATCH", report["errors"])


if __name__ == "__main__":
    unittest.main()
