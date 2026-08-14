from __future__ import annotations

import unittest

from tools.verify_research_governance import verify_research_governance


class ResearchGovernanceAcceptanceTests(unittest.TestCase):
    def test_research_governance_acceptance_is_complete_and_fail_closed(self) -> None:
        report = verify_research_governance()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 10)
        self.assertEqual(report["checks_passed"], 10)
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(report["profitability_state"], "UNPROVEN")
        self.assertFalse(report["strategy_family_selected"])
        self.assertFalse(report["strategy_edge_proven"])
        self.assertFalse(report["champion_promoted"])
        self.assertFalse(report["execution_simulator_calibrated"])
        self.assertFalse(report["production_backend_selected"])


if __name__ == "__main__":
    unittest.main()
