from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.verify_requirements_reconciliation import verify_requirements_reconciliation


ROOT = Path(__file__).resolve().parents[1]


class RequirementsReconciliationTests(unittest.TestCase):
    def _copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-requirements-reconciliation-"))
        self.addCleanup(shutil.rmtree, temp, True)
        repo = temp / "repo"
        shutil.copytree(ROOT, repo)
        return repo

    def test_current_boundary_is_safe_but_not_complete(self) -> None:
        report = verify_requirements_reconciliation(ROOT)

        self.assertTrue(report["ok"], report["errors"])
        self.assertFalse(report["reconciliation_complete"])
        self.assertFalse(report["promotion_allowed"])
        self.assertEqual(report["canonical_count"], 108)
        self.assertEqual(report["current_state_observed_count"], 119)
        self.assertEqual(report["local_memory_snapshot_count"], 111)
        self.assertIn("MEMORY_ROW_LEVEL_EVIDENCE_MISSING", report["blocking_findings"])
        self.assertIn("MEMORY_COUNT_CONFLICT_119_VS_111", report["blocking_findings"])

    def test_count_tampering_fails_closed(self) -> None:
        repo = self._copy_repo()
        state_path = repo / "authority/CURRENT_STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["neon_requirements_total_observed"] = 118
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        report = verify_requirements_reconciliation(repo)

        self.assertFalse(report["ok"])
        self.assertIn("CURRENT_STATE_COUNT_NOT_119", report["errors"])


if __name__ == "__main__":
    unittest.main()
