from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_c7_c9_design(root: Path) -> dict:
    errors: list[str] = []
    decisions = {}
    closures = {}
    for phase in ("C7", "C8", "C9"):
        try:
            decisions[phase] = json.loads((root / f"planning/phases/{phase}/{phase}_DECISIONS.json").read_text(encoding="utf-8"))
            closures[phase] = json.loads((root / f"planning/phases/{phase}/{phase}_REQUIREMENT_CLOSURE.json").read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{phase}: {exc}")
            decisions[phase] = {}
            closures[phase] = {}

    c7 = decisions["C7"].get("locks", {})
    if c7.get("future_filing_visibility") != "FORBIDDEN": errors.append("C7 future filing")
    if c7.get("point_estimate_only_valuation") != "FORBIDDEN": errors.append("C7 point estimate")
    if c7.get("restatement_overwrite") != "FORBIDDEN": errors.append("C7 restatement")

    c8 = decisions["C8"].get("locks", {})
    if c8.get("future_observation_visibility") != "FORBIDDEN": errors.append("C8 future observation")
    if c8.get("lower_detail_validates_higher_detail") is not False: errors.append("C8 fidelity")
    if c8.get("surface_consistency_checks_required") is not True: errors.append("C8 surface")

    c9 = decisions["C9"].get("locks", {})
    if c9.get("latest_revision_used_historically") != "FORBIDDEN": errors.append("C9 revised history")
    if c9.get("single_unverified_item_escalates_authority") != "FORBIDDEN": errors.append("C9 single item")
    if c9.get("fast_path_bypasses_control") is not False: errors.append("C9 fast path")
    if c9.get("event_source_selected") is not False: errors.append("C9 source selection")

    for phase in ("C7", "C8", "C9"):
        if decisions[phase].get("phase") != phase: errors.append(f"{phase} phase")
        for artifact in closures[phase].get("artifacts", []):
            if not (root / artifact).is_file(): errors.append(f"missing {artifact}")

    return {"ok": not errors, "errors": errors, "phases": ["C7", "C8", "C9"]}


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
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C7/C7_DECISIONS.json", lambda d: d["locks"].__setitem__("future_filing_visibility", "ALLOWED")); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_point_estimate_only_valuation_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C7/C7_DECISIONS.json", lambda d: d["locks"].__setitem__("point_estimate_only_valuation", "ALLOWED")); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_future_observation_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C8/C8_DECISIONS.json", lambda d: d["locks"].__setitem__("future_observation_visibility", "ALLOWED")); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_lower_detail_cannot_validate_higher_detail(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C8/C8_DECISIONS.json", lambda d: d["locks"].__setitem__("lower_detail_validates_higher_detail", True)); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_surface_checks_are_required(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C8/C8_DECISIONS.json", lambda d: d["locks"].__setitem__("surface_consistency_checks_required", False)); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_revised_history_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("latest_revision_used_historically", "ALLOWED")); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_single_unverified_item_cannot_escalate_authority(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("single_unverified_item_escalates_authority", "ALLOWED")); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_fast_path_cannot_bypass_controls(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("fast_path_bypasses_control", True)); self.assertFalse(validate_c7_c9_design(repo)["ok"])

    def test_source_selection_is_rejected(self) -> None:
        repo = self.copy_repo(); self.mutate(repo, "planning/phases/C9/C9_DECISIONS.json", lambda d: d["locks"].__setitem__("event_source_selected", True)); self.assertFalse(validate_c7_c9_design(repo)["ok"])


if __name__ == "__main__":
    unittest.main()
