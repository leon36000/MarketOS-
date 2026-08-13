from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_c1_design import validate_c1_design

ROOT = Path(__file__).resolve().parents[1]


class C1DesignTests(unittest.TestCase):
    def _copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c1-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    @staticmethod
    def _edit_json(repo: Path, relative: str, edit) -> None:
        path = repo / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        edit(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_c1_design_passes(self) -> None:
        report = validate_c1_design(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["profile_count"], 5)
        self.assertEqual(report["requirement_count"], 11)

    def test_public_ingress_is_rejected(self) -> None:
        repo = self._copy_repo()
        self._edit_json(repo, "planning/phases/C1/C1_DECISIONS.json", lambda data: data["deployment_profiles"][0].__setitem__("public_ingress", True))
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("public ingress" in error.lower() for error in report["errors"]))

    def test_k3s_cannot_become_mandatory(self) -> None:
        repo = self._copy_repo()
        def mutate(data):
            next(p for p in data["deployment_profiles"] if p["profile_id"] == "cluster-k3s")["mandatory"] = True
        self._edit_json(repo, "planning/phases/C1/C1_DECISIONS.json", mutate)
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("cluster-k3s must remain optional" in error for error in report["errors"]))

    def test_secret_readback_is_rejected(self) -> None:
        repo = self._copy_repo()
        self._edit_json(repo, "planning/phases/C1/C1_DECISIONS.json", lambda data: data["secret_tiers"][0].__setitem__("browser_readback", True))
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("browser readback" in error.lower() for error in report["errors"]))

    def test_global_application_adoption_is_rejected(self) -> None:
        repo = self._copy_repo()
        self._edit_json(repo, "planning/phases/C1/C1_DECISIONS.json", lambda data: data["application_candidates"][0].__setitem__("status", "ADOPTED"))
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("globally adopt" in error.lower() for error in report["errors"]))

    def test_backup_without_restore_cannot_be_verified(self) -> None:
        repo = self._copy_repo()
        self._edit_json(repo, "planning/phases/C1/C1_DECISIONS.json", lambda data: data["backup_rules"].__setitem__("backup_without_restore_status", "VERIFIED"))
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("backup without restore" in error.lower() for error in report["errors"]))

    def test_missing_requirement_mapping_is_rejected(self) -> None:
        repo = self._copy_repo()
        self._edit_json(repo, "planning/phases/C1/C1_REQUIREMENT_CLOSURE.json", lambda data: data["requirements"].pop())
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("requirement closure mismatch" in error.lower() for error in report["errors"]))

    def test_missing_mapped_artifact_is_rejected(self) -> None:
        repo = self._copy_repo()
        (repo / "docs/architecture/C1_BACKUP_RESTORE_DR.md").unlink()
        report = validate_c1_design(repo)
        self.assertFalse(report["ok"])
        self.assertTrue(any("missing artifact" in error.lower() for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
