from __future__ import annotations

import unittest

from tools.verify_data_foundation import verify_data_foundation


class DataFoundationAcceptanceTests(unittest.TestCase):
    def test_data_foundation_acceptance_is_complete_and_fail_closed(self) -> None:
        report = verify_data_foundation()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 8)
        self.assertEqual(report["checks_passed"], 8)
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(report["provider_selected"], False)
        self.assertEqual(report["production_storage_engine_selected"], False)


if __name__ == "__main__":
    unittest.main()
