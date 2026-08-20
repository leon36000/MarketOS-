from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TakeoverGateTests(unittest.TestCase):
    def test_takeover_gate_starts_at_the_authoritative_active_phase(self) -> None:
        state = json.loads((ROOT / "authority/CURRENT_STATE.json").read_text(encoding="utf-8"))
        gate = json.loads(
            (ROOT / "authority/CLAUDE_CODE_TAKEOVER_GATE.json").read_text(encoding="utf-8")
        )

        self.assertEqual(gate["start_phase"], state["planning_phase"])
        self.assertEqual(gate["finish_phase"], "C16")
        self.assertEqual(gate["locks"]["live_trading"], state["live_trading_state"])
        self.assertEqual(gate["locks"]["profitability"], state["profitability_state"])

        required_reads = set(gate["must_read"])
        self.assertTrue(
            {
                "authority/CURRENT_STATE.json",
                "planning/PHASE_INDEX.json",
                "planning/phases/C13/PHASE_BRIEF.md",
                "planning/phases/C14/PHASE_BRIEF.md",
                "planning/phases/C15/PHASE_BRIEF.md",
                "planning/phases/C16/PHASE_BRIEF.md",
            }.issubset(required_reads)
        )


if __name__ == "__main__":
    unittest.main()
