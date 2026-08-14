from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_c7_c9_design import validate_c7_c9_design

ROOT = Path(__file__).resolve().parents[1]


class C7C9DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c7-c9-"))
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
        report = validate_c7_c9_design(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["phases"], ["C7", "C8", "C9"])

    def test_future_filing_amendment_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C7/C7_DECISIONS.json", lambda d: d["locks"].__setitem__("future_filing_visibility", "ALLOWED"))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_point_estimate_only_valuation_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C7/C7_DECISIONS.json", lambda d: d["locks"].__setitem__("point_estimate_only_valuation", "ALLOWED"))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_future_bar_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C8/C8_DECISIONS.json", lambda d: d["locks"].__setitem__("future_bar_visibility", "ALLOWED"))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_lower_fidelity_fill_cannot_close_higher_gate(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C8/C8_DECISIONS.json", lambda d: d["locks"].__setitem__("lower_fidelity_promotes_higher_gate", True))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_options_surface_without_arbitrage_checks_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C8/C8_DECISIONS.json", lambda d: d["locks"].__setitem__("surface_arbitrage_checks_required", False))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_revised_macro_history_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("current_revised_macro_for_history", "ALLOWED"))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_single_social_post_cannot_increase_risk(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("single_post_risk_increase", "ALLOWED"))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_fast_path_cannot_bypass_risk(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("fast_path_bypasses_risk", True))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_provider_selection_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("news_provider_selected", True))
        self.assertFalse(validate_c7_c9_design(repo)["ok"])


if __name__ == "__main__":
    unittest.main()
