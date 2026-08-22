from __future__ import annotations

from pathlib import Path
import unittest

# Intentionally imports a verifier that does not exist until RED is observed.
from tools.verify_architecture_reconciliation import verify_architecture_reconciliation


class ArchitectureReconciliationAcceptanceTests(unittest.TestCase):
    def test_pr14_target_architecture_is_reconciled_fail_closed(self) -> None:
        report = verify_architecture_reconciliation(Path("."))

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(
            report["pr14_head_sha"],
            "bd3bf2823d6e731ece5ed8d66570d196be42b560",
        )
        self.assertEqual(
            report["pr20_base_head_sha"],
            "b05dd6004f60cc20b76c2c5c86c3ba6046401180",
        )
        self.assertFalse(report["pr14_merge_safe"])
        self.assertFalse(report["pr14_exact_head_ci_green"])
        self.assertEqual(report["verified_execution_slices"], 6)
        self.assertEqual(report["implementation_nodes_complete"], 0)
        self.assertEqual(report["canonical_requirements"], 108)
        self.assertEqual(report["memory_requirements_observed"], 119)
        self.assertFalse(report["stale_closure_refs_treated_as_resolved"])
        self.assertIn("C13_RUNTIME_CONTRACTS", report["critical_open_gaps"])
        self.assertIn("C14_COCKPIT_AND_OPERABILITY", report["critical_open_gaps"])
        self.assertIn("C15_QUALIFICATION", report["critical_open_gaps"])
        self.assertNotIn("PROOF_BINDING", report["critical_open_gaps"])
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(report["profitability_state"], "UNPROVEN")


if __name__ == "__main__":
    unittest.main()
