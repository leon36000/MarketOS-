from __future__ import annotations

import unittest

from tools.verify_market_data import verify_market_data


class MarketDataAcceptanceTests(unittest.TestCase):
    def test_market_data_acceptance_is_complete_and_fail_closed(self) -> None:
        report = verify_market_data()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checks_total"], 8)
        self.assertEqual(report["checks_passed"], 8)
        self.assertEqual(report["live_trading_state"], "HARD_LOCKED")
        self.assertFalse(report["provider_selected"])
        self.assertFalse(report["production_feed_qualified"])


if __name__ == "__main__":
    unittest.main()
