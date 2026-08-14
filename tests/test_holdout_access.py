from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.experiments import (
    AccessReceipt,
    DatasetAccessPolicy,
    DatasetPartition,
    DatasetRole,
    ExperimentLedger,
)


class HiddenHoldoutAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-holdout-access-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.path = self.temp / "experiments.sqlite"
        self.ledger = ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.policy = DatasetAccessPolicy(
            policy_id="dataset-access-v1",
            version=1,
            hidden_holdout_id="holdout-2026-final",
        )

    def receipt(
        self,
        receipt_id: str,
        role: DatasetRole,
        partition: DatasetPartition,
        purpose: str,
        *,
        requested_at_ns: int = 1_000,
    ) -> AccessReceipt:
        decision = self.policy.authorize(
            role=role,
            partition=partition,
            purpose=purpose,
            requested_at_ns=requested_at_ns,
        )
        return AccessReceipt.from_decision(receipt_id=receipt_id, decision=decision)

    def test_candidate_optimizer_and_model_council_cannot_read_hidden_holdout(self) -> None:
        cases = (
            (DatasetRole.CANDIDATE_GENERATOR, "CANDIDATE_GENERATION"),
            (DatasetRole.OPTIMIZER, "OPTIMIZATION"),
            (DatasetRole.MODEL_COUNCIL, "CANDIDATE_REVIEW"),
        )
        for index, (role, purpose) in enumerate(cases, start=1):
            with self.subTest(role=role):
                receipt = self.receipt(
                    f"denied-{index}",
                    role,
                    DatasetPartition.HIDDEN_HOLDOUT,
                    purpose,
                )
                self.assertFalse(receipt.allowed)
                self.assertEqual(receipt.reason, "HIDDEN_HOLDOUT_ACCESS_FORBIDDEN")
                self.assertEqual(receipt.hidden_holdout_id, "holdout-2026-final")

    def test_prompt_embedding_and_memory_systems_cannot_read_hidden_holdout(self) -> None:
        for index, role in enumerate(
            (
                DatasetRole.PROMPT_SYSTEM,
                DatasetRole.EMBEDDING_SYSTEM,
                DatasetRole.MEMORY_SYSTEM,
            ),
            start=1,
        ):
            receipt = self.receipt(
                f"context-denied-{index}",
                role,
                DatasetPartition.HIDDEN_HOLDOUT,
                "CONTEXT_ENRICHMENT",
            )
            self.assertFalse(receipt.allowed)
            self.assertEqual(receipt.reason, "HIDDEN_HOLDOUT_ACCESS_FORBIDDEN")

    def test_independent_evaluator_only_gets_holdout_for_final_evaluation(self) -> None:
        allowed = self.receipt(
            "allowed-final",
            DatasetRole.INDEPENDENT_EVALUATOR,
            DatasetPartition.HIDDEN_HOLDOUT,
            "FINAL_EVALUATION",
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.reason, "INDEPENDENT_FINAL_EVALUATION")
        denied = self.receipt(
            "denied-exploration",
            DatasetRole.INDEPENDENT_EVALUATOR,
            DatasetPartition.HIDDEN_HOLDOUT,
            "CANDIDATE_EXPLORATION",
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "HIDDEN_HOLDOUT_PURPOSE_FORBIDDEN")

    def test_non_holdout_partitions_are_available_but_still_audited(self) -> None:
        receipt = self.receipt(
            "train-access",
            DatasetRole.CANDIDATE_GENERATOR,
            DatasetPartition.TRAIN,
            "CANDIDATE_GENERATION",
        )
        self.assertTrue(receipt.allowed)
        self.assertEqual(receipt.reason, "NON_HOLDOUT_ACCESS")
        self.assertTrue(self.ledger.append_access_receipt(receipt))
        self.assertEqual(self.ledger.access_receipts(), (receipt,))

    def test_denied_attempts_are_append_only_queryable_evidence(self) -> None:
        denied = self.receipt(
            "denied-audit",
            DatasetRole.OPTIMIZER,
            DatasetPartition.HIDDEN_HOLDOUT,
            "OPTIMIZATION",
        )
        self.assertFalse(denied.allowed)
        self.assertTrue(self.ledger.append_access_receipt(denied))
        self.assertFalse(self.ledger.append_access_receipt(denied))
        self.assertEqual(self.ledger.access_receipts(), (denied,))
        self.assertFalse(hasattr(self.ledger, "delete_access_receipt"))

    def test_conflicting_receipt_id_is_rejected(self) -> None:
        first = self.receipt(
            "receipt-conflict",
            DatasetRole.CANDIDATE_GENERATOR,
            DatasetPartition.TRAIN,
            "CANDIDATE_GENERATION",
        )
        second = self.receipt(
            "receipt-conflict",
            DatasetRole.OPTIMIZER,
            DatasetPartition.TRAIN,
            "OPTIMIZATION",
        )
        self.ledger.append_access_receipt(first)
        with self.assertRaises(DuplicateConflict):
            self.ledger.append_access_receipt(second)
        self.assertEqual(self.ledger.access_receipts(), (first,))

    def test_access_policy_and_receipt_hashes_are_stable(self) -> None:
        decision = self.policy.authorize(
            role=DatasetRole.CANDIDATE_GENERATOR,
            partition=DatasetPartition.TRAIN,
            purpose="CANDIDATE_GENERATION",
            requested_at_ns=1_000,
        )
        receipt = AccessReceipt.from_decision(
            receipt_id="stable-receipt",
            decision=decision,
        )
        self.assertEqual(decision.policy_sha256, self.policy.sha256())
        self.assertEqual(receipt.decision_sha256, decision.sha256())
        self.assertEqual(receipt.sha256(), receipt.sha256())
        self.assertEqual(receipt.live_trading_state, "HARD_LOCKED")

    def test_database_forbids_access_receipt_update_or_delete(self) -> None:
        receipt = self.receipt(
            "locked-receipt",
            DatasetRole.CANDIDATE_GENERATOR,
            DatasetPartition.HIDDEN_HOLDOUT,
            "CANDIDATE_GENERATION",
        )
        self.ledger.append_access_receipt(receipt)
        connection = sqlite3.connect(self.path)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_ACCESS_RECEIPTS"):
            connection.execute(
                "UPDATE experiment_access_receipts SET record_json = ? WHERE receipt_id = ?",
                ("{}", receipt.receipt_id),
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_ACCESS_RECEIPTS"):
            connection.execute(
                "DELETE FROM experiment_access_receipts WHERE receipt_id = ?",
                (receipt.receipt_id,),
            )
        connection.close()

    def test_idempotent_receipt_redelivery_verifies_stored_content(self) -> None:
        receipt = self.receipt(
            "corrupt-receipt",
            DatasetRole.OPTIMIZER,
            DatasetPartition.HIDDEN_HOLDOUT,
            "OPTIMIZATION",
        )
        self.ledger.append_access_receipt(receipt)
        self.ledger.close()
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER experiment_access_receipts_no_update")
        connection.execute(
            "UPDATE experiment_access_receipts SET record_json = ? WHERE receipt_id = ?",
            ('{"receipt_id":"tampered"}', receipt.receipt_id),
        )
        connection.commit()
        connection.close()
        self.ledger = ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)
        with self.assertRaisesRegex(InvariantViolation, "ACCESS_RECEIPT_HASH_MISMATCH"):
            self.ledger.append_access_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
