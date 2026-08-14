from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "C10": {"AUD-MKT-001", "AUD-MKT-003", "AUD-DAT-003", "AUD-DAT-005", "AUD-DAT-007", "AUD-DAT-008", "AUD-DAT-009", "AUD-AI-013"},
    "C11": {"AUD-DAT-004", "AUD-DAT-007", "AUD-AI-008", "AUD-AI-009"},
    "C12": {"AUD-MKT-014", "AUD-AI-001", "AUD-AI-005", "AUD-AI-006", "AUD-AI-007", "AUD-AI-010", "AUD-AI-012", "AUD-AI-013", "AUD-RSK-008"},
}


def validate_c10_c12(root: Path) -> dict:
    errors: list[str] = []
    decisions: dict[str, dict] = {}
    closures: dict[str, dict] = {}

    for phase in ("C10", "C11", "C12"):
        try:
            decisions[phase] = json.loads((root / f"planning/phases/{phase}/{phase}_DECISIONS.json").read_text(encoding="utf-8"))
            closures[phase] = json.loads((root / f"planning/phases/{phase}/{phase}_REQUIREMENT_CLOSURE.json").read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{phase}: {exc}")
            decisions[phase] = {}
            closures[phase] = {}

        if decisions[phase].get("phase") != phase:
            errors.append(f"{phase} phase")
        if decisions[phase].get("status") != "DESIGN_GATE_PASS":
            errors.append(f"{phase} decision status")
        if closures[phase].get("status") != "DESIGN_GATE_PASS":
            errors.append(f"{phase} closure status")

        locks = decisions[phase].get("locks", {})
        if locks.get("live_trading") != "HARD_LOCKED":
            errors.append(f"{phase} live")
        if locks.get("profitability") != "UNPROVEN":
            errors.append(f"{phase} profit")

        observed_ids = set(closures[phase].get("requirement_ids", []))
        if observed_ids != REQUIRED[phase]:
            errors.append(f"{phase} requirements")
        for artifact in closures[phase].get("artifacts", []):
            if not (root / artifact).is_file():
                errors.append(f"{phase} missing artifact: {artifact}")

        boundary = closures[phase].get("hard_boundary", {})
        if boundary.get("live_trading") != "HARD_LOCKED" or boundary.get("profitability") != "UNPROVEN":
            errors.append(f"{phase} boundary")

    c10 = decisions["C10"].get("locks", {})
    if c10.get("hidden_holdout_access") != "FORBIDDEN": errors.append("C10 holdout")
    if c10.get("trial_deletion") != "FORBIDDEN": errors.append("C10 trials")
    if c10.get("synthetic_result_promotes") is not False: errors.append("C10 synthetic")
    if c10.get("no_trade_baseline_required") is not True: errors.append("C10 baseline")
    if c10.get("champion_promoted") is not False: errors.append("C10 champion")

    c11 = decisions["C11"].get("locks", {})
    if c11.get("historical_replay_authority") is not True: errors.append("C11 replay")
    if c11.get("synthetic_promotes_strategy") is not False: errors.append("C11 synthetic")
    if c11.get("online_rl_exploration") != "FORBIDDEN": errors.append("C11 online RL")
    if c11.get("world_model_selected") is not False: errors.append("C11 model")

    c12 = decisions["C12"].get("locks", {})
    if c12.get("model_direct_financial_authority") != "FORBIDDEN": errors.append("C12 authority")
    if c12.get("equal_vote_consensus") != "FORBIDDEN": errors.append("C12 vote")
    if c12.get("secret_readback") != "FORBIDDEN": errors.append("C12 secret")
    if c12.get("memory_future_visibility") != "FORBIDDEN": errors.append("C12 memory")
    if c12.get("self_promotion") != "FORBIDDEN": errors.append("C12 promotion")
    if c12.get("champion_and_evaluator_immutable") is not True: errors.append("C12 immutability")

    return {"ok": not errors, "errors": errors, "phases": ["C10", "C11", "C12"], "requirement_count": sum(len(ids) for ids in REQUIRED.values())}


class C10C12DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c10-c12-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    def mutate_lock(self, phase: str, key: str, value) -> dict:
        repo = self.copy_repo()
        path = repo / f"planning/phases/{phase}/{phase}_DECISIONS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["locks"][key] = value
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return validate_c10_c12(repo)

    def test_current_design_passes(self) -> None:
        report = validate_c10_c12(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["requirement_count"], 21)

    def test_hidden_holdout_access_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C10", "hidden_holdout_access", "ALLOWED")["ok"])

    def test_trial_deletion_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C10", "trial_deletion", "ALLOWED")["ok"])

    def test_synthetic_promotion_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C11", "synthetic_promotes_strategy", True)["ok"])

    def test_online_rl_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C11", "online_rl_exploration", "ALLOWED")["ok"])

    def test_equal_vote_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C12", "equal_vote_consensus", "ALLOWED")["ok"])

    def test_memory_lookahead_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C12", "memory_future_visibility", "ALLOWED")["ok"])

    def test_self_promotion_is_rejected(self) -> None:
        self.assertFalse(self.mutate_lock("C12", "self_promotion", "ALLOWED")["ok"])

    def test_missing_requirement_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "planning/phases/C12/C12_REQUIREMENT_CLOSURE.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["requirement_ids"].pop()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c10_c12(repo)["ok"])

    def test_missing_artifact_is_rejected(self) -> None:
        repo = self.copy_repo()
        (repo / "docs/architecture/C10_STRATEGY_FACTORY.md").unlink()
        self.assertFalse(validate_c10_c12(repo)["ok"])


if __name__ == "__main__":
    unittest.main()
