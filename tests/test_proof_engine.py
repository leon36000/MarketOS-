from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.verify_proof_engine import verify_proof_engine


ROOT = Path(__file__).resolve().parents[1]


class ProofEngineTests(unittest.TestCase):
    def _copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-proof-engine-"))
        self.addCleanup(shutil.rmtree, temp, True)
        repo = temp / "repo"
        shutil.copytree(ROOT, repo)
        return repo

    def test_current_repository_proof_policy_passes(self) -> None:
        report = verify_proof_engine(ROOT)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 13)
        self.assertEqual(report["checks_passed"], 13)

    def test_missing_policy_fails_closed(self) -> None:
        repo = self._copy_repo()
        (repo / "planning/architecture/PROOF_ENGINE_POLICY.json").unlink()

        report = verify_proof_engine(repo)

        self.assertFalse(report["ok"])
        self.assertIn("MISSING_PROOF_POLICY", report["errors"])

    def test_missing_authority_source_fails_closed(self) -> None:
        repo = self._copy_repo()
        policy_path = repo / "planning/architecture/PROOF_ENGINE_POLICY.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["source_authority_paths"].append("authority/not-present.json")
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_engine(repo)

        self.assertFalse(report["ok"])
        self.assertIn("SOURCE_AUTHORITY_PATH_MISSING:authority/not-present.json", report["errors"])

    def test_weakened_live_lock_fails_closed(self) -> None:
        repo = self._copy_repo()
        state_path = repo / "authority/CURRENT_STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["live_trading_state"] = "ENABLED"
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_engine(repo)

        self.assertFalse(report["ok"])
        self.assertIn("LIVE_TRADING_LOCK_WEAKENED", report["errors"])

    def test_missing_requirements_boundary_fails_closed(self) -> None:
        repo = self._copy_repo()
        (repo / "planning/architecture/REQUIREMENTS_108_119_RECONCILIATION.json").unlink()

        report = verify_proof_engine(repo)

        self.assertFalse(report["ok"])
        self.assertIn("REQUIREMENTS_RECONCILIATION_BOUNDARY_INVALID", report["errors"])

    def test_missing_proof_binding_fails_closed(self) -> None:
        repo = self._copy_repo()
        (repo / "planning/architecture/PROOF_BINDING.json").unlink()

        report = verify_proof_engine(repo)

        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["PROOF_BINDING"])
        self.assertIn("PROOF_BINDING_INVALID", report["errors"])


if __name__ == "__main__":
    unittest.main()
