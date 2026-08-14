from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_c10_c12_design import validate_c10_c12_design

ROOT = Path(__file__).resolve().parents[1]


class C10C12DesignTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="marketos-c10-c12-"))
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
        report = validate_c10_c12_design(ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["phases"], ["C10", "C11", "C12"])

    def test_hidden_holdout_cannot_be_exposed(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C10/C10_DECISIONS.json", lambda d: d["locks"].__setitem__("hidden_holdout_visible_to_generator", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_trial_registry_cannot_be_disabled(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C10/C10_DECISIONS.json", lambda d: d["locks"].__setitem__("complete_trial_registry_required", False))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_synthetic_fixture_cannot_promote(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C10/C10_DECISIONS.json", lambda d: d["locks"].__setitem__("synthetic_fixture_can_promote", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_synthetic_world_cannot_be_authority(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C11/C11_DECISIONS.json", lambda d: d["locks"].__setitem__("synthetic_world_authoritative", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_online_exploration_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C11/C11_DECISIONS.json", lambda d: d["locks"].__setitem__("online_exploration_allowed", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_policy_promotion_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C11/C11_DECISIONS.json", lambda d: d["locks"].__setitem__("policy_promoted", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_unpinned_latest_model_is_rejected(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C12/C12_DECISIONS.json", lambda d: d["locks"].__setitem__("latest_model_alias_allowed", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_model_output_cannot_be_authority(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C12/C12_DECISIONS.json", lambda d: d["locks"].__setitem__("model_output_authoritative", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_model_alone_cannot_promote_memory(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C12/C12_DECISIONS.json", lambda d: d["locks"].__setitem__("model_alone_can_promote_memory", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])

    def test_recursive_lab_cannot_modify_champion(self) -> None:
        repo = self.copy_repo()
        self.mutate(repo, "planning/phases/C12/C12_DECISIONS.json", lambda d: d["locks"].__setitem__("recursive_lab_can_modify_active_champion", True))
        self.assertFalse(validate_c10_c12_design(repo)["ok"])


if __name__ == "__main__":
    unittest.main()
