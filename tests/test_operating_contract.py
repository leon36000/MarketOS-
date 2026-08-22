from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.verify_operating_contract import verify_operating_contract


ROOT = Path(__file__).resolve().parents[1]


class OperatingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._trusted_reviewer_patch = patch.dict(
            os.environ,
            {"MARKETOS_TRUSTED_REVIEWERS": "external-sol-reviewer"},
        )
        self._trusted_reviewer_patch.start()
        self.addCleanup(self._trusted_reviewer_patch.stop)
        self._github_source_patch = patch(
            "tools.verify_operating_contract._fetch_github_review",
            return_value=self._github_review_source(),
        )
        self._github_source_patch.start()
        self.addCleanup(self._github_source_patch.stop)

    def _copy_fixture(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="marketos-operating-contract-"))
        self.addCleanup(shutil.rmtree, temp_dir, True)
        shutil.copytree(
            ROOT,
            temp_dir / "repo",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__"),
        )
        return temp_dir / "repo"

    def _git_value(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _base_sha(self) -> str:
        return self._git_value(
            "rev-parse",
            "--verify",
            "--end-of-options",
            "refs/remotes/origin/codex/pr14-pr20-reconciliation-proof",
        )

    def _write_authority_bytes(self, data: bytes, prefix: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".json",
            prefix=prefix,
            dir=ROOT / "authority",
            delete=False,
        )
        with handle:
            handle.write(data)
        path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def _write_authority_json(self, payload: object, prefix: str) -> Path:
        return self._write_authority_bytes(
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            prefix,
        )

    def _github_review_source(self, **overrides: object) -> dict[str, object]:
        source: dict[str, object] = {
            "id": 12345,
            "user": {"login": "external-sol-reviewer"},
            "state": "APPROVED",
            "commit_id": self._git_value("rev-parse", "HEAD"),
            "html_url": "https://github.com/leon36000/MarketOS-/pull/30#pullrequestreview-12345",
            "body": (
                "MARKETOS_REVIEW_REPOSITORY=leon36000/MarketOS-\n"
                f"MARKETOS_REVIEW_BASE_SHA={self._base_sha()}\n"
                f"MARKETOS_REVIEW_HEAD_SHA={self._git_value('rev-parse', 'HEAD')}\n"
                f"MARKETOS_REVIEW_TREE_SHA={self._git_value('rev-parse', 'HEAD^{tree}')}\n"
                "MARKETOS_REVIEW_VERDICT=APPROVE\n"
                "MARKETOS_REVIEW_MODEL=GPT-5.6 Sol\n"
                "MARKETOS_REVIEW_CONTEXT=independent_blind\n"
                "MARKETOS_REVIEW_FINDINGS_JSON=[]\n"
                "Independent analysis and reproducible evidence are attached."
            ),
        }
        source.update(overrides)
        return source

    def _receipt(self, **overrides: object) -> Path:
        payload: dict[str, object] = {
            "repository": "leon36000/MarketOS-",
            "reviewer_model": "GPT-5.6 Sol",
            "review_context": "independent_blind",
            "reviewed_base_sha": self._base_sha(),
            "reviewed_head_sha": self._git_value("rev-parse", "HEAD"),
            "reviewed_tree_sha": self._git_value("rev-parse", "HEAD^{tree}"),
            "pull_request": 30,
            "review_id": 12345,
            "review_url": "https://github.com/leon36000/MarketOS-/pull/30#pullrequestreview-12345",
            "reviewer_login": "external-sol-reviewer",
            "verdict": "APPROVE",
            "findings": [],
        }
        payload.update(overrides)
        artifact = {
            "review_id": payload["review_id"],
            "pull_request": payload["pull_request"],
            "review_url": payload["review_url"],
            "reviewer_login": payload["reviewer_login"],
            "repository": payload["repository"],
            "reviewer_model": payload["reviewer_model"],
            "review_context": payload["review_context"],
            "reviewed_base_sha": payload["reviewed_base_sha"],
            "reviewed_head_sha": payload["reviewed_head_sha"],
            "reviewed_tree_sha": payload["reviewed_tree_sha"],
            "verdict": payload["verdict"],
            "analysis": (
                "Independent review reproduced the exact SHA, policy, locks, "
                "tests and failure paths before the verdict."
            ),
            "evidence": [
                {
                    "command": "python3 tools/verify_operating_contract.py --root . --json",
                    "result": "PASS on the exact review tree",
                }
            ],
            "findings": payload["findings"],
        }
        artifact_path = self._write_authority_json(
            artifact,
            "marketos-review-artifact-",
        )
        payload["review_artifact_path"] = str(artifact_path.relative_to(ROOT))
        payload["review_artifact_sha256"] = hashlib.sha256(
            artifact_path.read_bytes()
        ).hexdigest()
        return self._write_authority_json(payload, "marketos-review-")

    def _minimal_receipt(self) -> Path:
        return self._write_authority_json(
            {
                "repository": "leon36000/MarketOS-",
                "reviewer_model": "GPT-5.6 Sol",
                "review_context": "independent_blind",
                "reviewed_base_sha": self._base_sha(),
                "reviewed_head_sha": self._git_value("rev-parse", "HEAD"),
                "reviewed_tree_sha": self._git_value("rev-parse", "HEAD^{tree}"),
                "verdict": "APPROVE",
                "findings": [],
            },
            "marketos-minimal-review-",
        )

    def test_current_policy_is_consumed_and_preserves_hard_locks(self) -> None:
        report = verify_operating_contract(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(report["review_required"])
        self.assertFalse(report["review_bound"])
        self.assertFalse(report["promotion_allowed"])
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(report["profitability_state"], "UNPROVEN")

    def test_contradictory_parallel_limit_is_rejected_by_consumer(self) -> None:
        repo = self._copy_fixture()
        path = repo / "AGENTS.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "LUNA_PARALLEL_LIMIT=2", "LUNA_PARALLEL_LIMIT=3"
            ),
            encoding="utf-8",
        )
        report = verify_operating_contract(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(error.startswith("POLICY_MARKER_MISMATCH:") for error in report["errors"])
        )

    def test_merge_policy_cannot_be_weakened_in_one_surface(self) -> None:
        repo = self._copy_fixture()
        path = repo / "CLAUDE.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "MERGE_REQUIRES_EXACT_SHA_REVIEW=true",
                "MERGE_REQUIRES_EXACT_SHA_REVIEW=false",
            ),
            encoding="utf-8",
        )
        report = verify_operating_contract(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(error.startswith("POLICY_MARKER_MISMATCH:") for error in report["errors"])
        )

    def test_empty_policy_object_fails_closed(self) -> None:
        repo = self._copy_fixture()
        (repo / "authority" / "OPERATING_POLICY.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        report = verify_operating_contract(repo)
        self.assertFalse(report["ok"])
        self.assertIn("OPERATING_POLICY_IDENTITY_OR_RULES_INVALID", report["errors"])

    def test_policy_rule_tampering_fails_closed(self) -> None:
        repo = self._copy_fixture()
        path = repo / "authority" / "OPERATING_POLICY.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["review"]["allowed_models"] = ["GPT-5.6 Terra"]
        path.write_text(json.dumps(policy), encoding="utf-8")
        report = verify_operating_contract(repo)
        self.assertFalse(report["ok"])
        self.assertIn("OPERATING_POLICY_IDENTITY_OR_RULES_INVALID", report["errors"])

    def test_contradictory_prose_limit_is_rejected_by_consumer(self) -> None:
        repo = self._copy_fixture()
        path = repo / "PROJECT_INSTRUCTIONS.md"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\nAgents may run three Luna subagents at once.\n",
            encoding="utf-8",
        )
        report = verify_operating_contract(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                error.startswith("POLICY_SEMANTIC_CONTRADICTION:")
                for error in report["errors"]
            )
        )

    def test_merge_without_review_prose_is_rejected_by_consumer(self) -> None:
        repo = self._copy_fixture()
        path = repo / "CLAUDE.md"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\nThe integrator may merge without a Sol review.\n",
            encoding="utf-8",
        )
        report = verify_operating_contract(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(
                error.startswith("POLICY_SEMANTIC_CONTRADICTION:")
                for error in report["errors"]
            )
        )

    def test_stale_review_receipt_is_rejected_against_current_tree(self) -> None:
        receipt = self._receipt(reviewed_head_sha="0" * 40)
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_HEAD_SHA_MISMATCH", report["errors"])

    def test_review_receipt_outside_repository_is_rejected(self) -> None:
        report = verify_operating_contract(
            ROOT,
            review_receipt=Path(tempfile.gettempdir()),
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_RECEIPT_OUTSIDE_ROOT", report["errors"])

    def test_minimal_self_declared_receipt_is_rejected(self) -> None:
        receipt = self._minimal_receipt()
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_ID_INVALID", report["errors"])

    def test_tampered_review_artifact_digest_is_rejected(self) -> None:
        receipt = self._receipt()
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        artifact = ROOT / payload["review_artifact_path"]
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_ARTIFACT_DIGEST_MISMATCH", report["errors"])

    def test_external_review_source_head_mismatch_is_rejected(self) -> None:
        receipt = self._receipt()
        source = self._github_review_source(commit_id="0" * 40)
        with patch(
            "tools.verify_operating_contract._fetch_github_review",
            return_value=source,
        ):
            report = verify_operating_contract(
                ROOT,
                review_receipt=receipt,
                expected_base_sha=self._base_sha(),
            )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_SOURCE_HEAD_MISMATCH", report["errors"])

    def test_external_owner_review_is_rejected(self) -> None:
        receipt = self._receipt()
        source = self._github_review_source(
            user={"login": "leon36000"}
        )
        with patch(
            "tools.verify_operating_contract._fetch_github_review",
            return_value=source,
        ):
            report = verify_operating_contract(
                ROOT,
                review_receipt=receipt,
                expected_base_sha=self._base_sha(),
            )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_SOURCE_SELF_REVIEW_REJECTED", report["errors"])

    def test_review_receipt_symlink_is_rejected(self) -> None:
        receipt = self._receipt()
        link = ROOT / "authority" / ".marketos-review-link.json"
        link.symlink_to(receipt)
        self.addCleanup(link.unlink, missing_ok=True)
        report = verify_operating_contract(
            ROOT,
            review_receipt=link,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertIn("REVIEW_RECEIPT_SYMLINK_REJECTED", report["errors"])

    def test_review_receipt_parent_symlink_is_rejected_by_openat(self) -> None:
        receipt = self._receipt()
        alias = ROOT / "authority-alias"
        alias.symlink_to(ROOT / "authority", target_is_directory=True)
        self.addCleanup(alias.unlink, missing_ok=True)
        report = verify_operating_contract(
            ROOT,
            review_receipt=alias / receipt.name,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertIn("REVIEW_RECEIPT_READ_FAILED", report["errors"])

    def test_oversized_review_receipt_is_rejected(self) -> None:
        receipt = self._write_authority_bytes(
            b"0" * (64 * 1024 + 1),
            "marketos-oversized-review-",
        )
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertIn("REVIEW_RECEIPT_TOO_LARGE", report["errors"])

    def test_reachable_but_non_target_base_is_rejected(self) -> None:
        receipt = self._receipt(
            reviewed_base_sha=self._git_value("rev-parse", "HEAD")
        )
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_BASE_TARGET_MISMATCH", report["errors"])

    def test_blocking_finding_cannot_hide_inside_nonblocking_verdict(self) -> None:
        receipt = self._receipt(
            verdict="APPROVE_WITH_NONBLOCKING_FINDINGS",
            findings=[
                {
                    "severity": "HIGH",
                    "blocking": True,
                    "summary": "unsafe merge path",
                }
            ],
        )
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["review_bound"])
        self.assertIn("REVIEW_BLOCKING_FINDING", report["errors"])

    def test_valid_review_receipt_binds_exact_base_head_and_tree(self) -> None:
        receipt = self._receipt()
        report = verify_operating_contract(
            ROOT,
            review_receipt=receipt,
            expected_base_sha=self._base_sha(),
        )
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(report["review_bound"])
        self.assertTrue(report["merge_authorized"])
        self.assertFalse(report["promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
