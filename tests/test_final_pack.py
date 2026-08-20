from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from tools.build_claude_pack import PackError, build_and_verify, build_pack, verify_archive


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

    def test_output_path_is_confined_to_system_temp_directory(self) -> None:
        unsafe = ROOT.parent / f".marketos-unsafe-output-{id(self)}.zip"
        self.assertFalse(unsafe.exists())
        self.addCleanup(unsafe.unlink, missing_ok=True)

        with self.assertRaises(PackError):
            build_pack(self.source, unsafe, validate=False, require_clean=False)

    def test_broken_output_symlink_is_rejected(self) -> None:
        target = self.temp / "missing-target.zip"
        symlink = self.temp / "broken-output.zip"
        try:
            os.symlink(target, symlink)
        except OSError:
            self.skipTest("symbolic links are unavailable on this platform")

        with self.assertRaises(PackError):
            build_pack(self.source, symlink, validate=False, require_clean=False)

    def test_sha_sidecar_symlink_is_rejected(self) -> None:
        output = self.temp / "sha-sidecar.zip"
        target = self.temp / "sha-sidecar-target.txt"
        target.write_text("keep", encoding="utf-8")
        try:
            os.symlink(target, Path(str(output) + ".sha256"))
        except OSError:
            self.skipTest("symbolic links are unavailable on this platform")

        with self.assertRaises(PackError):
            build_and_verify(self.source, output, require_clean=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_verification_sidecar_symlink_is_rejected(self) -> None:
        output = self.temp / "verification-sidecar.zip"
        target = self.temp / "verification-sidecar-target.txt"
        target.write_text("keep", encoding="utf-8")
        try:
            os.symlink(target, Path(str(output) + ".verification.json"))
        except OSError:
            self.skipTest("symbolic links are unavailable on this platform")

        with self.assertRaises(PackError):
            build_and_verify(self.source, output, require_clean=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

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
            read_first = handle.read("READ_FIRST.md").decode("utf-8")
        self.assertIn("READ_FIRST.md", names)
        self.assertIn("PACK_MANIFEST.json", names)
        self.assertIn("PACK_PROVENANCE.json", names)
        self.assertIn("PACK_SBOM.spdx.json", names)
        self.assertNotIn("repository/.git", names)
        self.assertIn("Never execute validators or any other code extracted from this pack", read_first)

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

    def test_archive_verification_never_executes_extracted_validator(self) -> None:
        archive = self.build("validator-payload.zip")
        marker = self.temp / "archive-validator-executed"
        with zipfile.ZipFile(archive) as handle:
            members = {info.filename: handle.read(info.filename) for info in handle.infolist()}

        malicious = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        ).encode("utf-8")
        members["repository/tools/validate_repository.py"] = malicious
        manifest = json.loads(members["PACK_MANIFEST.json"])
        entry = next(item for item in manifest["files"] if item["path"] == "repository/tools/validate_repository.py")
        entry["bytes"] = len(malicious)
        entry["sha256"] = hashlib.sha256(malicious).hexdigest()
        members["PACK_MANIFEST.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for name, data in sorted(members.items()):
                handle.writestr(name, data)

        report = verify_archive(archive, run_repository_checks=True)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verification_mode"], "structural-only")
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
