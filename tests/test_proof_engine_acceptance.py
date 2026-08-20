from __future__ import annotations

import unittest

from tools.verify_proof_engine import verify_proof_engine


class ProofEngineAcceptanceTests(unittest.TestCase):
    def test_proof_engine_v2_is_complete_and_fail_closed(self) -> None:
        report = verify_proof_engine()

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 13)
        self.assertEqual(report["checks_passed"], 13)
        self.assertTrue(report["checks"]["PROOF_BINDING"])
        self.assertTrue(report["exact_sha_binding_required"])
        self.assertTrue(report["artifact_resolution_required"])
        self.assertTrue(report["source_authority_required"])
        self.assertTrue(report["append_only_ledger"])
        self.assertFalse(report["stale_or_missing_reference_promotable"])
        self.assertFalse(report["failed_or_mismatched_ci_promotable"])
        self.assertFalse(report["proof_engine_can_unlock_live_trading"])
        self.assertFalse(report["proof_engine_can_prove_profitability"])
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(report["profitability_state"], "UNPROVEN")


if __name__ == "__main__":
    unittest.main()
