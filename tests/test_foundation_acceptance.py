from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FoundationAcceptanceTests(unittest.TestCase):
    def test_foundation_verifier_passes_all_contracts(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [sys.executable, "tools/verify_foundation.py", "--json"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["check_count"], 8)
        self.assertTrue(all(check["ok"] for check in report["checks"]))
        self.assertEqual(report["live_trading"], "HARD_LOCKED")
        self.assertEqual(report["profitability"], "UNPROVEN")

    def test_replay_cli_is_deterministic_across_processes(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        command = [
            sys.executable,
            "-m",
            "marketos",
            "replay",
            "--input",
            "examples/paper_scenario.jsonl",
            "--risk",
            "config/paper-risk.json",
            "--initial-cash",
            "1000.00",
        ]
        first = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(first.stdout)["fingerprint"], json.loads(second.stdout)["fingerprint"])


if __name__ == "__main__":
    unittest.main()
