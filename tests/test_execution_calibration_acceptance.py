from __future__ import annotations

import unittest

from tools.verify_execution_calibration import verify_execution_calibration


class ExecutionCalibrationAcceptanceTests(unittest.TestCase):
    def test_execution_calibration_acceptance_is_complete_and_fail_closed(self) -> None:
        report = verify_execution_calibration()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 10)
        self.assertEqual(report["checks_passed"], 10)
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(report["profitability_state"], "UNPROVEN")
        self.assertFalse(report["execution_simulator_calibrated"])
        self.assertFalse(report["observed_broker_feed_qualified"])
        self.assertFalse(report["capacity_qualified"])
        self.assertFalse(report["capital_authorized"])
        self.assertFalse(report["strategy_edge_proven"])
        self.assertFalse(report["production_backend_selected"])


if __name__ == "__main__":
    unittest.main()
