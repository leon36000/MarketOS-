from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "marketos", *args],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_validate_config_returns_machine_readable_lock_state(self) -> None:
        result = self.run_cli("validate-config", "--risk", "config/paper-risk.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["live_trading"], "HARD_LOCKED")
        self.assertEqual(len(payload["risk_limits_sha256"]), 64)

    def test_replay_scenario_writes_auditable_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-cli-") as temp_dir:
            db = Path(temp_dir) / "run.sqlite3"
            result = self.run_cli(
                "replay",
                "--input", "examples/paper_scenario.jsonl",
                "--risk", "config/paper-risk.json",
                "--db", str(db),
                "--initial-cash", "1000.00",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "COMPLETE")
            self.assertEqual(payload["cash"]["minor_units"], 104895)
            self.assertEqual(payload["live_trading"], "HARD_LOCKED")
            self.assertTrue(db.is_file())

    def test_float_token_in_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-config-") as temp_dir:
            source = json.loads((ROOT / "config/paper-risk.json").read_text())
            source["max_order_notional"] = 100.5
            path = Path(temp_dir) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            result = self.run_cli("validate-config", "--risk", str(path))
            self.assertNotEqual(result.returncode, 0)
            error = json.loads(result.stderr)
            self.assertFalse(error["ok"])
            self.assertIn("FLOAT_TOKEN_FORBIDDEN", error["error"])

    def test_live_flag_is_structurally_rejected(self) -> None:
        result = self.run_cli(
            "replay",
            "--input", "examples/paper_scenario.jsonl",
            "--risk", "config/paper-risk.json",
            "--live",
        )
        self.assertNotEqual(result.returncode, 0)
        error = json.loads(result.stderr)
        self.assertIn("LIVE_TRADING_HARD_LOCKED", error["error"])


if __name__ == "__main__":
    unittest.main()
