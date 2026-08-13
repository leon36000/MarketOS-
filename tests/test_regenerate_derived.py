from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.regenerate_derived import regenerate

ROOT = Path(__file__).resolve().parents[1]


class RegenerateDerivedTests(unittest.TestCase):
    def _copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-derived-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    def test_current_repository_is_reconciled(self) -> None:
        report = regenerate(ROOT, check=True)
        self.assertTrue(report["ok"], report["changed"])

    def test_regeneration_repairs_manifest_and_indexes(self) -> None:
        repo = self._copy_repo()
        readme = repo / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        index_path = repo / "requirements" / "REQUIREMENTS_INDEX.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        data["source_csv_sha256"] = "0" * 64
        index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        stale = regenerate(repo, check=True)
        self.assertFalse(stale["ok"])
        self.assertIn("MANIFEST.json", stale["changed"])
        self.assertIn("requirements/REQUIREMENTS_INDEX.json", stale["changed"])
        self.assertTrue(regenerate(repo, check=False)["ok"])
        self.assertTrue(regenerate(repo, check=True)["ok"])

    def test_unmanifested_file_enters_manifest(self) -> None:
        repo = self._copy_repo()
        path = repo / "docs" / "new-evidence.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence", encoding="utf-8")
        regenerate(repo, check=False)
        manifest = json.loads((repo / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertIn("docs/new-evidence.md", {entry["path"] for entry in manifest["files"]})


if __name__ == "__main__":
    unittest.main()
