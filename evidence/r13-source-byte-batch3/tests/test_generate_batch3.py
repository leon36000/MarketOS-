from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "generate_batch3.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("generate_batch3", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Batch3ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_module()

    def test_source_registry_has_exactly_fourteen_unique_pinned_files(self) -> None:
        specs = self.mod.SOURCE_SPECS
        self.assertEqual(14, len(specs))
        keys = {(s.repo, s.commit, s.path) for s in specs}
        self.assertEqual(14, len(keys))
        self.assertTrue(all(len(s.commit) == 40 for s in specs))
        self.assertTrue(all(s.repo and s.path and s.role for s in specs))

    def test_git_blob_sha_matches_git_object_contract(self) -> None:
        payload = b"MarketOS exact bytes\n"
        expected = hashlib.sha1(
            f"blob {len(payload)}\0".encode("ascii") + payload
        ).hexdigest()
        self.assertEqual(expected, self.mod.git_blob_sha1(payload))

    def test_build_receipt_rejects_blob_identity_mismatch(self) -> None:
        source = {
            "id": "bad",
            "repo": "example/example",
            "commit": "0" * 40,
            "path": "bad.txt",
            "role": "NEGATIVE_TEST",
            "expected_git_blob_sha1": "1" * 40,
            "data": b"different bytes",
            "metadata_size": len(b"different bytes"),
        }
        with self.assertRaisesRegex(ValueError, "Git blob SHA-1 mismatch"):
            self.mod.build_source_receipt(source, retrieved_at="2026-08-25T00:00:00Z")

    def test_build_source_receipt_records_exact_hashes_and_fail_closed_rights(self) -> None:
        payload = b"canonical bytes\n"
        source = {
            "id": "good",
            "repo": "example/example",
            "commit": "a" * 40,
            "path": "good.txt",
            "role": "POSITIVE_TEST",
            "expected_git_blob_sha1": self.mod.git_blob_sha1(payload),
            "data": payload,
            "metadata_size": len(payload),
        }
        receipt = self.mod.build_source_receipt(
            source, retrieved_at="2026-08-25T00:00:00Z"
        )
        self.assertEqual(hashlib.sha256(payload).hexdigest(), receipt["sha256"])
        self.assertEqual(len(payload), receipt["byte_count"])
        self.assertTrue(receipt["git_blob_match"])
        self.assertFalse(receipt["raw_bytes_shared"])
        self.assertFalse(receipt["redistribution_right_asserted"])
        self.assertFalse(receipt["ai_ml_training_right_asserted"])
        self.assertNotIn("data", receipt)

    def test_receipt_only_bundle_is_deterministic_and_excludes_raw_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt_dir = root / "receipt"
            receipt_dir.mkdir()
            (receipt_dir / "receipt.json").write_text(
                json.dumps({"status": "PASS"}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (receipt_dir / "README.md").write_text("receipt only\n", encoding="utf-8")
            first = root / "first.zip"
            second = root / "second.zip"
            self.mod.build_deterministic_zip(receipt_dir, first)
            self.mod.build_deterministic_zip(receipt_dir, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as zf:
                names = zf.namelist()
                self.assertEqual(sorted(names), names)
                self.assertEqual({"README.md", "receipt.json"}, set(names))
                self.assertIsNone(zf.testzip())

    def test_status_requires_fourteen_verified_sources_and_target_thirty(self) -> None:
        receipts = []
        for index in range(14):
            payload = f"source-{index}\n".encode()
            receipts.append(
                {
                    "id": f"source-{index}",
                    "repo": "example/example",
                    "commit": "a" * 40,
                    "path": f"source-{index}.txt",
                    "role": "TEST",
                    "git_blob_sha1": self.mod.git_blob_sha1(payload),
                    "computed_git_blob_sha1": self.mod.git_blob_sha1(payload),
                    "git_blob_match": True,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_count": len(payload),
                    "utf8_valid": True,
                    "raw_bytes_shared": False,
                    "redistribution_right_asserted": False,
                    "ai_ml_training_right_asserted": False,
                }
            )
        status = self.mod.build_status(receipts, bundle={"sha256": "b" * 64, "byte_count": 1})
        self.assertEqual(16, status["retrieval"]["observed_before"])
        self.assertEqual(14, status["retrieval"]["verified_in_batch"])
        self.assertEqual(30, status["retrieval"]["authoritative_observed_after"])
        self.assertEqual(30, status["retrieval"]["planning_target"])
        self.assertTrue(status["retrieval"]["target_achieved"])
        self.assertFalse(status["r13_phase_event_appended"])
        self.assertEqual(0, status["technology_adoptions"])
        self.assertEqual("HARD_LOCKED", status["hard_locks"]["live_trading"])
        self.assertEqual("UNPROVEN", status["hard_locks"]["profitability"])


if __name__ == "__main__":
    unittest.main()
