from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.verify_proof_binding import verify_proof_binding


ROOT = Path(__file__).resolve().parents[1]


class ProofBindingTests(unittest.TestCase):
    def _copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-proof-binding-"))
        self.addCleanup(shutil.rmtree, temp, True)
        repo = temp / "repo"
        shutil.copytree(ROOT, repo)
        return repo

    def _ledger(self, repo: Path) -> tuple[Path, dict[str, object]]:
        path = repo / "planning/architecture/PROOF_BINDING.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    def test_current_repository_binding_passes_without_promotion_authority(self) -> None:
        report = verify_proof_binding(ROOT)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["bindings_checked"], 7)
        self.assertEqual(report["artifact_bindings_checked"], 3)
        self.assertFalse(report["promotion_allowed"])

    def test_missing_binding_ledger_fails_closed(self) -> None:
        repo = self._copy_repo()
        (repo / "planning/architecture/PROOF_BINDING.json").unlink()

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("MISSING_PROOF_BINDING", report["errors"])

    def test_bound_artifact_tamper_fails_closed(self) -> None:
        repo = self._copy_repo()
        path = repo / "authority/CURRENT_STATE.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["last_verified_at"] = "2099-01-01"
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("SOURCE_ARTIFACT_HASH_MISMATCH:authority/CURRENT_STATE.json", report["errors"])

    def test_exact_head_sha_tamper_fails_closed(self) -> None:
        repo = self._copy_repo()
        path, ledger = self._ledger(repo)
        ledger["execution_bindings"][0]["head_sha"] = "0" * 40  # type: ignore[index]
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("EXECUTION_BINDING_HEAD_MISMATCH:14", report["errors"])

    def test_ci_receipt_tamper_fails_closed(self) -> None:
        repo = self._copy_repo()
        path, ledger = self._ledger(repo)
        ledger["execution_bindings"][6]["ci_run_ids"] = [999999999]  # type: ignore[index]
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("EXECUTION_BINDING_CI_RECEIPTS_MISMATCH:20", report["errors"])

    def test_malformed_ci_receipt_fails_closed(self) -> None:
        repo = self._copy_repo()
        matrix_path = repo / "planning/architecture/PR14_PR20_RECONCILIATION.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix["execution_slices"][5]["ci_runs"].append("not-an-integer")
        matrix_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
        path, ledger = self._ledger(repo)
        ledger["artifact_bindings"][0]["sha256"] = hashlib.sha256(matrix_path.read_bytes()).hexdigest()  # type: ignore[index]
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("EXECUTION_BINDING_CI_RECEIPTS_MISMATCH:20", report["errors"])

    def test_promotion_flag_fails_closed(self) -> None:
        repo = self._copy_repo()
        path, ledger = self._ledger(repo)
        ledger["promotion_allowed"] = True
        path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("PROMOTION_FLAG_ENABLED", report["errors"])

    def test_bound_artifact_symlink_is_rejected(self) -> None:
        repo = self._copy_repo()
        external = repo.parent / "external-current-state.json"
        external.write_text((repo / "authority/CURRENT_STATE.json").read_text(encoding="utf-8"), encoding="utf-8")
        artifact = repo / "authority/CURRENT_STATE.json"
        artifact.unlink()
        try:
            os.symlink(external, artifact)
        except OSError:
            self.skipTest("symbolic links are unavailable on this platform")

        report = verify_proof_binding(repo)

        self.assertFalse(report["ok"])
        self.assertIn("SOURCE_ARTIFACT_SYMLINK_FORBIDDEN:authority/CURRENT_STATE.json", report["errors"])


if __name__ == "__main__":
    unittest.main()
