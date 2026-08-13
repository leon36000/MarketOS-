from __future__ import annotations

import importlib.util
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
        path = repo / "planning" / "phases" / "C1" / "EXECUTION_CONTRACT.md"
        path.write_text(path.read_text(encoding="utf-8").replace("## Rollback", "## Removed"), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("Rollback" in e for e in report["errors"]))

    def test_manifest_byte_count_mismatch_is_rejected(self) -> None:
        repo = self._copy_fixture()
        path = repo / "MANIFEST.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["bytes"] += 1
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("manifest byte count mismatch" in e.lower() for e in report["errors"]))

    def test_unmanifested_file_is_rejected(self) -> None:
        repo = self._copy_fixture()
        extra = repo / "docs" / "UNTRACKED.md"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("untracked evidence", encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("unmanifested file" in e.lower() for e in report["errors"]))

    def test_missing_phase_reference_is_rejected(self) -> None:
        repo = self._copy_fixture()
        (repo / "authority" / "CLAUDE_CODE_TAKEOVER_GATE.json").unlink(missing_ok=True)
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("takeover gate" in e.lower() or "referenced path" in e.lower() for e in report["errors"]))

    def test_claude_bootstrap_command_must_reference_existing_tool(self) -> None:
        repo = self._copy_fixture()
        claude = repo / "CLAUDE.md"
        claude.write_text(claude.read_text(encoding="utf-8").replace("tools/validate_repository.py", "tools/does_not_exist.py"), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("claude bootstrap tool" in e.lower() for e in report["errors"]))

    def test_takeover_gate_commands_and_read_paths_must_exist(self) -> None:
        repo = self._copy_fixture()
        path = repo / "authority" / "CLAUDE_CODE_TAKEOVER_GATE.json"
        gate = json.loads(path.read_text(encoding="utf-8"))
        gate["verify_command"] = "python tools/not_real.py"
        gate["must_read"].append("missing/context.md")
        path.write_text(json.dumps(gate, indent=2), encoding="utf-8")
        report = validate_repository(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("takeover verify tool" in e.lower() for e in report["errors"]))
        self.assertTrue(any("takeover must_read" in e.lower() for e in report["errors"]))

    def test_neon_tools_are_import_safe_without_runtime_dependencies(self) -> None:
        for relative in ("tools/ingest_requirements.py", "tools/verify_neon_memory.py"):
            path = FIXTURE_ROOT / relative
            spec = importlib.util.spec_from_file_location(f"marketos_test_{path.stem}", path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

    def test_execution_contract_count_matches_repository(self) -> None:
        report = validate_repository(FIXTURE_ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["execution_contract_count"], 10)


if __name__ == "__main__":
    unittest.main()
