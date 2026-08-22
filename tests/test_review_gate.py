from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.verify_github_review import (
    _select_exact_review,
    verify_github_review,
)


ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40


def _review(**overrides: object) -> dict[str, object]:
    verdict = str(overrides.pop("review_verdict", "APPROVE"))
    findings = overrides.pop("findings", [])
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
            f"MARKETOS_REVIEW_VERDICT={verdict}\n"
            "MARKETOS_REVIEW_MODEL=GPT-5.6 Sol\n"
            "MARKETOS_REVIEW_CONTEXT=independent_blind\n"
            f"MARKETOS_REVIEW_FINDINGS_JSON={json.dumps(findings, sort_keys=True, separators=(',', ':'))}\n"
            "Independent review evidence."
        ),
    }
    review.update(overrides)
    return review


class ReviewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._trusted_reviewer_patch = patch.dict(
            os.environ,
            {"MARKETOS_TRUSTED_REVIEWERS": "external-sol-reviewer"},
        )
        self._trusted_reviewer_patch.start()
        self.addCleanup(self._trusted_reviewer_patch.stop)

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
        def select_stale_review() -> dict[str, object]:
            return _select_exact_review(
                [_review(commit_id="0" * 40)],
                repository="leon36000/MarketOS-",
                pull_request=30,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                owner_login="leon36000",
            )

        with self.assertRaisesRegex(ValueError, "NO_EXTERNAL_EXACT_HEAD_APPROVAL"):
            select_stale_review()

    def test_selector_rejects_withdrawn_latest_review(self) -> None:
        with self.assertRaisesRegex(ValueError, "NO_EXTERNAL_EXACT_HEAD_APPROVAL"):
            _select_exact_review(
                [_review(id=1), _review(id=2, state="CHANGES_REQUESTED")],
                repository="leon36000/MarketOS-",
                pull_request=30,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                owner_login="leon36000",
            )

    def test_selector_rejects_untrusted_reviewer(self) -> None:
        with self.assertRaisesRegex(ValueError, "NO_EXTERNAL_EXACT_HEAD_APPROVAL"):
            _select_exact_review(
                [_review(user={"login": "arbitrary-external-user"})],
                repository="leon36000/MarketOS-",
                pull_request=30,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                owner_login="leon36000",
            )

    def test_selector_accepts_permitted_nonblocking_findings(self) -> None:
        selected = _select_exact_review(
            [_review(
                review_verdict="APPROVE_WITH_NONBLOCKING_FINDINGS",
                findings=[{"severity": "LOW", "summary": "Documentation wording"}],
            )],
            repository="leon36000/MarketOS-",
            pull_request=30,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            tree_sha=TREE_SHA,
            owner_login="leon36000",
        )
        self.assertEqual(selected["verdict"], "APPROVE_WITH_NONBLOCKING_FINDINGS")
        self.assertEqual(len(selected["findings"]), 1)

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
        base_seed = git("rev-parse", "HEAD")
        git("checkout", "-b", "feature", "--quiet")
        readme = repo / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nmerge-ref fixture\n", encoding="utf-8")
        git("add", "README.md")
        git("commit", "-m", "feature", "--quiet")
        feature_head = git("rev-parse", "HEAD")
        feature_tree = git("rev-parse", "HEAD^{tree}")
        git("checkout", "-b", "integration-base", base_seed, "--quiet")
        (repo / "merge-ref-base-only.txt").write_text("base-only\n", encoding="utf-8")
        git("add", "merge-ref-base-only.txt")
        git("commit", "-m", "integration base", "--quiet")
        base = git("rev-parse", "HEAD")
        git(
            "update-ref",
            "refs/remotes/origin/codex/pr14-pr20-reconciliation-proof",
            base,
        )
        git("checkout", "-b", "merge", base, "--quiet")
        git("merge", "--no-ff", "feature", "-m", "merge", "--quiet")
        merge_head = git("rev-parse", "HEAD")
        merge_tree = git("rev-parse", "HEAD^{tree}")
        git("update-ref", "refs/pull/30/merge", merge_head)
        git("checkout", "--detach", "refs/pull/30/merge", "--quiet")
        self.assertEqual(git("rev-parse", "HEAD"), merge_head)
        self.assertNotEqual(merge_tree, feature_tree)

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
                "MARKETOS_REVIEW_FINDINGS_JSON=[]\n"
                "Independent merge-ref fixture evidence."
            ),
        )

        with patch(
            "tools.verify_github_review._fetch_github_reviews",
            return_value=[source],
        ):
            report = verify_github_review(
                repo,
                repository="leon36000/MarketOS-",
                pull_request=30,
                expected_base_sha=base,
                expected_head_sha=feature_head,
            )
        self.assertFalse(report["ok"])
        self.assertIn("CURRENT_HEAD_EVENT_MISMATCH", report["errors"])

        with patch(
            "tools.verify_github_review._fetch_github_reviews",
            return_value=[source],
        ):
            merge_report = verify_github_review(
                repo,
                repository="leon36000/MarketOS-",
                pull_request=30,
                expected_base_sha=base,
                expected_head_sha=merge_head,
            )
        self.assertFalse(merge_report["ok"])
        self.assertIn("GITHUB_REVIEW_GATE_FAILED:ValueError", merge_report["errors"])


if __name__ == "__main__":
    unittest.main()
