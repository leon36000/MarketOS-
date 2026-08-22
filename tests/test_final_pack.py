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

    def build(self, name: str) -> Path:
        output = self.temp / name
        build_pack(ROOT, output, validate=False, require_clean=False)
        return output

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
        self.assertIn("repository/implementation/IMPLEMENTATION_DAG.json", names)
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

    def test_extracted_repository_validators_pass(self) -> None:
        archive = self.build("validated.zip")
        report = verify_archive(archive, run_repository_checks=True)
        self.assertTrue(report["validator_reports"]["repository"]["ok"])
        self.assertTrue(report["validator_reports"]["c16"]["ok"])


if __name__ == "__main__":
    unittest.main()
