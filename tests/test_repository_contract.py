from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_repository import validate_repository

FIXTURE_ROOT = Path(__file__).resolve().parents[1]

class RepositoryContractTests(unittest.TestCase):
    def _copy_fixture(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="marketos-contract-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(FIXTURE_ROOT, tmp / "repo", dirs_exist_ok=True)
        return tmp / "repo"

    def test_valid_repository_passes(self) -> None:
        report = validate_repository(FIXTURE_ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["requirements_count"], 108)
        self.assertEqual(report["planning_phase_count"], 16)

    def test_compact_requirement_index_is_supported(self) -> None:
        repo = self._copy_fixture()
        csv_path = repo / "requirements" / "REQUIREMENT_CROSSWALK.csv"
        csv_path.unlink(missing_ok=True)
        manifest_path = repo / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = [entry for entry in manifest["files"] if entry["path"] != "requirements/REQUIREMENT_CROSSWALK.csv"]
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        report = validate_repository(repo)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["requirements_count"], 108)

    def test_live_lock_weakening_is_rejected(self) -> None:
        repo = self._copy_fixture()
        state_path = repo / "authority" / "CURRENT_STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["live_trading_state"] = "ENABLED"
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("HARD_LOCKED" in e for e in report["errors"]))

    def test_duplicate_requirement_ids_are_rejected(self) -> None:
        repo = self._copy_fixture()
        index_path = repo / "requirements" / "REQUIREMENTS_INDEX.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        data["requirements"].append(dict(data["requirements"][0]))
        data["count"] += 1
        index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("duplicate requirement" in e.lower() for e in report["errors"]))

    def test_manifest_tamper_is_rejected(self) -> None:
        repo = self._copy_fixture()
        readme = repo / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\ntamper\n", encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("manifest hash mismatch" in e.lower() for e in report["errors"]))

    def test_missing_c1_contract_section_is_rejected(self) -> None:
        repo = self._copy_fixture()
        contract_path = repo / "planning" / "phases" / "C1" / "EXECUTION_CONTRACT.md"
        text = contract_path.read_text(encoding="utf-8")
        contract_path.write_text(text.replace("## Rollback", "## Removed"), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("Rollback" in e for e in report["errors"]))

if __name__ == "__main__":
    unittest.main()
