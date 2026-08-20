from __future__ import annotations

import shutil
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from tools.build_claude_pack import PackError, build_pack, verify_archive


ROOT = Path(__file__).resolve().parents[1]


class FinalPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-final-pack-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.source = self.temp / "repo"
        shutil.copytree(
            ROOT,
            self.source,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )
        self._git("init", "-q")
        self._git("config", "user.email", "codex-test@example.invalid")
        self._git("config", "user.name", "codex-test")
        self._git("add", "-A")
        self._git("commit", "-qm", "test: clean fixture")

    def _git(self, *args: str) -> None:
        import subprocess

        subprocess.run(["git", *args], cwd=self.source, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def build(self, name: str) -> Path:
        output = self.temp / name
        build_pack(self.source, output, validate=False, require_clean=False)
        return output

    def test_dirty_source_is_rejected_for_release_pack(self) -> None:
        readme = self.source / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

        with self.assertRaises(PackError):
            build_pack(self.source, self.temp / "dirty.zip", validate=False, require_clean=True)

    def test_two_builds_are_byte_identical(self) -> None:
        first = self.build("one.zip")
        second = self.build("two.zip")

        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_archive_layout_and_manifest_verify(self) -> None:
        archive = self.build("pack.zip")

        report = verify_archive(archive, run_repository_checks=False)

        self.assertTrue(report["ok"])
        with zipfile.ZipFile(archive) as handle:
            names = set(handle.namelist())
        self.assertIn("READ_FIRST.md", names)
        self.assertIn("PACK_MANIFEST.json", names)
        self.assertIn("PACK_PROVENANCE.json", names)
        self.assertIn("PACK_SBOM.spdx.json", names)
        self.assertNotIn("repository/.git", names)

    def test_duplicate_member_is_rejected(self) -> None:
        archive = self.build("tampered.zip")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "a") as handle:
                handle.writestr("READ_FIRST.md", b"tamper")

        with self.assertRaises(PackError):
            verify_archive(archive, run_repository_checks=False)

    def test_unsafe_member_is_rejected(self) -> None:
        archive = self.temp / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escape", b"bad")

        with self.assertRaises(PackError):
            verify_archive(archive, run_repository_checks=False)


if __name__ == "__main__":
    unittest.main()
