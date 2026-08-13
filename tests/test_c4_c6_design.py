from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_c4_c6_design(root: Path) -> dict:
    errors = []
    data = {}
    for phase in ("C4", "C5", "C6"):
        try:
            data[phase] = json.loads((root / f"planning/phases/{phase}/{phase}_DECISIONS.json").read_text())
        except Exception as exc:
            errors.append(f"{phase}: {exc}")
            data[phase] = {}
    for phase, value in data.items():
        locks = value.get("locks", {})
        if locks.get("live_trading") != "HARD_LOCKED": errors.append(f"{phase} live")
        if locks.get("profitability") != "UNPROVEN": errors.append(f"{phase} profit")
    if data["C4"].get("event_time", {}).get("elapsed_time_source") != "MONOTONIC_CLOCK": errors.append("C4 clock")
    if data["C4"].get("visual_bridge", {}).get("v5_state") != "HARD_BLOCKED": errors.append("C4 visual")
    c5 = data["C5"].get("locks", {})
    if c5.get("global_vendor_winner") != "FORBIDDEN": errors.append("C5 winner")
    if c5.get("fpga_purchase_authorized") is not False: errors.append("C5 FPGA")
    if c5.get("cpu_golden_oracle_fallback_required") is not True: errors.append("C5 fallback")
    c6 = data["C6"].get("locks", {})
    if c6.get("silent_numerical_repair") != "FORBIDDEN": errors.append("C6 repair")
    if c6.get("decision_equivalence_required") is not True: errors.append("C6 decision")
    if c6.get("no_trade_supported") is not True: errors.append("C6 no-trade")
    return {"ok": not errors, "errors": errors, "phases": ["C4", "C5", "C6"]}


class C4C6DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c4-c6-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    @staticmethod
    def mutate(repo: Path, relative: str, callback) -> None:
        path = repo / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        callback(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_current_design_passes(self) -> None:
        report = validate_c4_c6_design(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["phases"], ["C4", "C5", "C6"])

    def test_live_lock_weakening_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C4/C4_DECISIONS.json", lambda d: d["locks"].__setitem__("live_trading", "ENABLED")); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_wall_clock_elapsed_time_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C4/C4_DECISIONS.json", lambda d: d["event_time"].__setitem__("elapsed_time_source", "WALL_CLOCK")); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_visual_live_canary_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C4/C4_DECISIONS.json", lambda d: d["visual_bridge"].__setitem__("v5_state", "ENABLED")); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_global_vendor_winner_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C5/C5_DECISIONS.json", lambda d: d["locks"].__setitem__("global_vendor_winner", "NVIDIA")); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_fpga_purchase_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C5/C5_DECISIONS.json", lambda d: d["locks"].__setitem__("fpga_purchase_authorized", True)); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_cpu_fallback_cannot_be_removed(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C5/C5_DECISIONS.json", lambda d: d["locks"].__setitem__("cpu_golden_oracle_fallback_required", False)); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_silent_numerical_repair_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C6/C6_DECISIONS.json", lambda d: d["locks"].__setitem__("silent_numerical_repair", "ALLOWED")); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_decision_equivalence_cannot_be_disabled(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C6/C6_DECISIONS.json", lambda d: d["locks"].__setitem__("decision_equivalence_required", False)); self.assertFalse(validate_c4_c6_design(repo)["ok"])

    def test_no_trade_support_cannot_be_removed(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C6/C6_DECISIONS.json", lambda d: d["locks"].__setitem__("no_trade_supported", False)); self.assertFalse(validate_c4_c6_design(repo)["ok"])


if __name__ == "__main__": unittest.main()
