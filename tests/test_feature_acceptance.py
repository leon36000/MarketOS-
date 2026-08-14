from __future__ import annotations

import unittest

from tools.verify_feature_foundation import verify_feature_foundation


class FeatureFoundationAcceptanceTests(unittest.TestCase):
    def test_feature_foundation_is_complete_and_fail_closed(self) -> None:
        report = verify_feature_foundation()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 8)
        self.assertEqual(report["checks_passed"], 8)
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertFalse(report["calendar_provider_selected"])
        self.assertFalse(report["feature_backend_selected"])
        self.assertFalse(report["feature_edge_proven"])


if __name__ == "__main__":
    unittest.main()
