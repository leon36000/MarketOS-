from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.verify_operating_contract import verify_operating_contract


ROOT = Path(__file__).resolve().parents[1]


class OperatingContractTests(unittest.TestCase):
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

    def _receipt(self, **overrides: object) -> Path:
        payload: dict[str, object] = {
            "repository": "leon36000/MarketOS-",
            "reviewer_model": "GPT-5.6 Sol",
            "review_context": "independent_blind",
            "reviewed_base_sha": self._base_sha(),
            "reviewed_head_sha": self._git_value("rev-parse", "HEAD"),
            "reviewed_tree_sha": self._git_value("rev-parse", "HEAD^{tree}"),
            "verdict": "APPROVE",
            "findings": [],
        }
        payload.update(overrides)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="marketos-review-",
            dir=ROOT / "authority",
            delete=False,
        )
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        with handle:
            json.dump(payload, handle)
        return Path(handle.name)

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

    def test_reachable_but_non_target_base_is_rejected(self) -> None:
        receipt = self._receipt(
            reviewed_base_sha=self._git_value("rev-parse", "HEAD^")
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
