from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_c16_design import validate_c16_design

ROOT = Path(__file__).resolve().parents[1]


class C16DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c16-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    def test_current_design_passes(self) -> None:
        report = validate_c16_design(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["requirements_total"], 108)
        self.assertEqual(report["requirements_covered"], 108)
        self.assertEqual(report["design_phases_pass"], 16)
        self.assertEqual(report["implementation_nodes"], 49)
        self.assertEqual(report["implementation_nodes_completed"], 0)

    def test_live_lock_weakening_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "planning/phases/C16/C16_DECISIONS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["locks"]["live_trading"] = "ENABLED"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c16_design(repo)["ok"])

    def test_software_completion_claim_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "planning/phases/C16/C16_DECISIONS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["locks"]["software_implementation_complete"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c16_design(repo)["ok"])

    def test_completed_implementation_node_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "implementation/IMPLEMENTATION_DAG.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["nodes"][0]["status"] = "COMPLETE"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c16_design(repo)["ok"])

    def test_missing_requirement_coverage_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "planning/phases/C16/C16_REQUIREMENT_CLOSURE.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["global_audit"]["covered_requirement_ids"].pop()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c16_design(repo)["ok"])

    def test_dag_cycle_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "implementation/IMPLEMENTATION_DAG.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["nodes"][0]["depends_on"] = ["40"]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c16_design(repo)["ok"])

    def test_missing_pack_acceptance_artifact_is_rejected(self) -> None:
        repo = self.copy_repo()
        (repo / "docs/architecture/C16_BUILD_PACK_ACCEPTANCE.md").unlink()
        self.assertFalse(validate_c16_design(repo)["ok"])


if __name__ == "__main__":
    unittest.main()
