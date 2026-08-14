from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_c10_c12(root: Path) -> dict:
    errors: list[str] = []
    data = {}
    for phase in ("C10", "C11", "C12"):
        try:
            data[phase] = json.loads((root / f"planning/phases/{phase}/{phase}_DECISIONS.json").read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{phase}: {exc}")
            data[phase] = {}
        locks = data[phase].get("locks", {})
        if locks.get("live_trading") != "HARD_LOCKED": errors.append(f"{phase} live")
        if locks.get("profitability") != "UNPROVEN": errors.append(f"{phase} profit")

    c10 = data["C10"].get("locks", {})
    if c10.get("hidden_holdout_access") != "FORBIDDEN": errors.append("C10 holdout")
    if c10.get("trial_deletion") != "FORBIDDEN": errors.append("C10 trials")
    if c10.get("synthetic_result_promotes") is not False: errors.append("C10 synthetic")
    if c10.get("no_trade_baseline_required") is not True: errors.append("C10 baseline")
    if c10.get("champion_promoted") is not False: errors.append("C10 champion")

    c11 = data["C11"].get("locks", {})
    if c11.get("historical_replay_authority") is not True: errors.append("C11 replay")
    if c11.get("synthetic_promotes_strategy") is not False: errors.append("C11 synthetic")
    if c11.get("online_rl_exploration") != "FORBIDDEN": errors.append("C11 online RL")
    if c11.get("world_model_selected") is not False: errors.append("C11 model")

    c12 = data["C12"].get("locks", {})
    if c12.get("model_direct_financial_authority") != "FORBIDDEN": errors.append("C12 authority")
    if c12.get("equal_vote_consensus") != "FORBIDDEN": errors.append("C12 vote")
    if c12.get("secret_readback") != "FORBIDDEN": errors.append("C12 secret")
    if c12.get("memory_future_visibility") != "FORBIDDEN": errors.append("C12 memory")
    if c12.get("self_promotion") != "FORBIDDEN": errors.append("C12 promotion")
    if c12.get("champion_and_evaluator_immutable") is not True: errors.append("C12 immutability")

    for phase in ("C10", "C11", "C12"):
        if data[phase].get("phase") != phase: errors.append(f"{phase} phase")

    return {"ok": not errors, "errors": errors, "phases": ["C10", "C11", "C12"]}


class C10C12DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c10-c12-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    def mutate(self, phase: str, key: str, value) -> dict:
        repo = self.copy_repo()
        path = repo / f"planning/phases/{phase}/{phase}_DECISIONS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["locks"][key] = value
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return validate_c10_c12(repo)

    def test_current_design_passes(self) -> None:
        report = validate_c10_c12(ROOT)
        self.assertTrue(report["ok"], report["errors"])

    def test_hidden_holdout_access_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C10", "hidden_holdout_access", "ALLOWED")["ok"])

    def test_trial_deletion_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C10", "trial_deletion", "ALLOWED")["ok"])

    def test_synthetic_promotion_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C11", "synthetic_promotes_strategy", True)["ok"])

    def test_online_rl_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C11", "online_rl_exploration", "ALLOWED")["ok"])

    def test_equal_vote_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C12", "equal_vote_consensus", "ALLOWED")["ok"])

    def test_memory_lookahead_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C12", "memory_future_visibility", "ALLOWED")["ok"])

    def test_self_promotion_is_rejected(self) -> None:
        self.assertFalse(self.mutate("C12", "self_promotion", "ALLOWED")["ok"])


if __name__ == "__main__":
    unittest.main()
