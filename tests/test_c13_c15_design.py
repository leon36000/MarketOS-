from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_c13_c15_design import validate_c13_c15_design

ROOT = Path(__file__).resolve().parents[1]


class C13C15DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c13-c15-"))
        self.addCleanup(shutil.rmtree, temp, True)
        shutil.copytree(ROOT, temp / "repo", dirs_exist_ok=True)
        return temp / "repo"

    @staticmethod
    def mutate(repo: Path, phase: str, key: str, value) -> dict:
        path = repo / f"planning/phases/{phase}/{phase}_DECISIONS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["locks"][key] = value
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return validate_c13_c15_design(repo)

    def test_current_design_passes(self) -> None:
        report = validate_c13_c15_design(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["phases"], ["C13", "C14", "C15"])
        self.assertEqual(report["requirement_count"], 39)

    def test_model_cannot_override_risk_veto(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C13", "model_can_override_risk_veto", "ALLOWED")["ok"])

    def test_unreconciled_books_cannot_increase_risk(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C13", "unreconciled_books_allow_risk_increase", True)["ok"])

    def test_unknown_broker_capability_fails_closed(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C13", "unknown_broker_capability_default", "ALLOW")["ok"])

    def test_mutable_accounting_balances_are_rejected(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C13", "mutable_accounting_balances", "ALLOWED")["ok"])

    def test_cockpit_claims_require_evidence(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C14", "material_claims_require_evidence", False)["ok"])

    def test_secret_readback_is_rejected(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C14", "secret_readback", "ALLOWED")["ok"])

    def test_mobile_risk_increase_is_rejected(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C14", "mobile_risk_increase", "ALLOWED")["ok"])

    def test_browser_direct_broker_route_is_rejected(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C14", "browser_direct_broker_route", "ALLOWED")["ok"])

    def test_lifecycle_stage_skip_is_rejected(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C15", "stage_skip", "ALLOWED")["ok"])

    def test_pnl_only_promotion_is_rejected(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C15", "pnl_only_promotion", "ALLOWED")["ok"])

    def test_canary_cannot_be_pre_authorized(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C15", "canary_authorized", True)["ok"])

    def test_replay_shadow_paper_must_continue(self) -> None:
        self.assertFalse(self.mutate(self.copy_repo(), "C15", "replay_shadow_paper_remain_on", False)["ok"])

    def test_missing_requirement_is_rejected(self) -> None:
        repo = self.copy_repo()
        path = repo / "planning/phases/C15/C15_REQUIREMENT_CLOSURE.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["requirement_ids"].pop()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertFalse(validate_c13_c15_design(repo)["ok"])

    def test_missing_artifact_is_rejected(self) -> None:
        repo = self.copy_repo()
        (repo / "docs/architecture/C13_RISK_KERNEL.md").unlink()
        self.assertFalse(validate_c13_c15_design(repo)["ok"])


if __name__ == "__main__":
    unittest.main()
