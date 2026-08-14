from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from marketos.datafabric import (
    DatasetPublisher,
    DatasetSpec,
    PublicationDenied,
    RawEvidenceStore,
    TemporalFact,
    TemporalFactStore,
    create_backup_manifest,
    verify_backup_manifest,
)
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy


class DataFabricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-datafabric-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    @staticmethod
    def rights() -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("storage", "historical_replay", "derived_data", "audit_reporting", "exit_export"):
            fields[field] = RightDecision.ALLOW
        return RightsPolicy("rights-1", fields)

    def test_raw_evidence_is_content_addressed_idempotent_and_tamper_evident(self) -> None:
        store = RawEvidenceStore(self.temp / "raw")
        first = store.put(
            b"issuer filing bytes",
            source_id="issuer",
            retrieved_at_ns=100,
            media_type="application/octet-stream",
            rights_policy_ids=("rights-1",),
        )
        second = store.put(
            b"issuer filing bytes",
            source_id="issuer",
            retrieved_at_ns=101,
            media_type="application/octet-stream",
            rights_policy_ids=("rights-1",),
        )
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(store.get(first.content_sha256), b"issuer filing bytes")
        self.assertEqual(len(store.receipts(first.content_sha256)), 2)
        self.assertTrue(store.verify(first.content_sha256))

        first.object_path.write_bytes(b"tampered")
        self.assertFalse(store.verify(first.content_sha256))
        with self.assertRaisesRegex(InvariantViolation, "RAW_EVIDENCE_HASH_MISMATCH"):
            store.get(first.content_sha256)

    def test_temporal_fact_queries_respect_knowledge_time(self) -> None:
        store = TemporalFactStore(self.temp / "facts.sqlite")
        self.addCleanup(store.close)
        v1 = TemporalFact(
            fact_id="fact-1",
            fact_key="listing:abc:status",
            version=1,
            valid_from_ns=0,
            valid_to_ns=None,
            available_to_strategy_at_ns=10,
            revision_time_ns=10,
            source_id="exchange",
            payload={"status": "ACTIVE"},
        )
        v2 = TemporalFact(
            fact_id="fact-1",
            fact_key="listing:abc:status",
            version=2,
            valid_from_ns=0,
            valid_to_ns=None,
            available_to_strategy_at_ns=20,
            revision_time_ns=20,
            source_id="exchange",
            payload={"status": "DELISTED"},
        )
        self.assertTrue(store.append(v1))
        self.assertTrue(store.append(v2))
        self.assertEqual(store.as_of("listing:abc:status", economic_time_ns=5, knowledge_time_ns=15), v1)
        self.assertEqual(store.as_of("listing:abc:status", economic_time_ns=5, knowledge_time_ns=25), v2)
        self.assertIsNone(store.as_of("listing:abc:status", economic_time_ns=5, knowledge_time_ns=9))
        self.assertEqual(len(store.history("fact-1")), 2)

    def test_temporal_fact_version_conflict_and_gap_fail(self) -> None:
        store = TemporalFactStore(self.temp / "facts.sqlite")
        self.addCleanup(store.close)
        v1 = TemporalFact("fact-1", "key", 1, 0, None, 10, 10, "source", {"value": 1})
        self.assertTrue(store.append(v1))
        self.assertFalse(store.append(v1))
        with self.assertRaises(DuplicateConflict):
            store.append(TemporalFact("fact-1", "key", 1, 0, None, 10, 10, "source", {"value": 2}))
        with self.assertRaisesRegex(InvariantViolation, "FACT_VERSION_SEQUENCE"):
            store.append(TemporalFact("fact-1", "key", 3, 0, None, 30, 30, "source", {"value": 3}))

    def dataset_spec(self, *, version: str = "v1") -> DatasetSpec:
        return DatasetSpec(
            dataset_id="security-master",
            version=version,
            schema_id="security-master@1",
            source_versions=("source@1",),
            economic_cutoff_ns=100,
            knowledge_cutoff_ns=110,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            dependency_lock_sha256="c" * 64,
            rights_policy_ids=("rights-1",),
            quality_report_id="quality-1",
            lineage_run_id="run-1",
        )

    def test_dataset_publication_is_atomic_gated_and_idempotent(self) -> None:
        publisher = DatasetPublisher(self.temp / "lake")
        spec = self.dataset_spec()
        with self.assertRaises(PublicationDenied):
            publisher.publish(
                spec,
                {"part-000.jsonl": b'{"id":1}\n'},
                rights_policies=(self.rights(),),
                quality_pass=False,
                lineage_complete=True,
            )
        self.assertEqual(publisher.list_versions("security-master"), ())

        first = publisher.publish(
            spec,
            {"part-000.jsonl": b'{"id":1}\n'},
            rights_policies=(self.rights(),),
            quality_pass=True,
            lineage_complete=True,
        )
        self.assertTrue(first.inserted)
        self.assertTrue(first.commit_path.is_file())
        self.assertEqual(publisher.list_versions("security-master"), ("v1",))
        manifest = json.loads(first.commit_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["content_root_sha256"], first.content_root_sha256)

        second = publisher.publish(
            spec,
            {"part-000.jsonl": b'{"id":1}\n'},
            rights_policies=(self.rights(),),
            quality_pass=True,
            lineage_complete=True,
        )
        self.assertFalse(second.inserted)
        self.assertEqual(second.content_root_sha256, first.content_root_sha256)
        with self.assertRaises(DuplicateConflict):
            publisher.publish(
                spec,
                {"part-000.jsonl": b'{"id":2}\n'},
                rights_policies=(self.rights(),),
                quality_pass=True,
                lineage_complete=True,
            )

    def test_unsafe_dataset_paths_never_become_visible(self) -> None:
        publisher = DatasetPublisher(self.temp / "lake")
        with self.assertRaisesRegex(InvariantViolation, "UNSAFE_DATASET_PATH"):
            publisher.publish(
                self.dataset_spec(),
                {"../escape": b"bad"},
                rights_policies=(self.rights(),),
                quality_pass=True,
                lineage_complete=True,
            )
        self.assertEqual(publisher.list_versions("security-master"), ())

    def test_backup_manifest_detects_corruption(self) -> None:
        root = self.temp / "recovery-source"
        root.mkdir()
        (root / "a.txt").write_text("alpha", encoding="utf-8")
        (root / "nested").mkdir()
        (root / "nested" / "b.bin").write_bytes(b"beta")
        manifest = create_backup_manifest(root)
        self.assertTrue(verify_backup_manifest(root, manifest).ok)
        (root / "a.txt").write_text("changed", encoding="utf-8")
        report = verify_backup_manifest(root, manifest)
        self.assertFalse(report.ok)
        self.assertIn("HASH_MISMATCH:a.txt", report.errors)


if __name__ == "__main__":
    unittest.main()
