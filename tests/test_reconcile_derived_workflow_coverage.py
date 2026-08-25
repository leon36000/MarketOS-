from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECONCILE_WORKFLOW = ROOT / ".github" / "workflows" / "reconcile-derived-files.yml"
MANIFEST = ROOT / "MANIFEST.json"


class ReconcileDerivedWorkflowCoverageTests(unittest.TestCase):
    def test_every_workflow_change_triggers_derived_reconciliation(self) -> None:
        workflow = RECONCILE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            '- ".github/workflows/**"',
            workflow,
            "workflow additions or edits must always trigger derived-file reconciliation",
        )

    def test_trusted_review_gate_files_are_manifested_after_regeneration(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn(".github/workflows/trusted-review-gate.yml", paths)
        self.assertIn("tools/trusted_review_gate.py", paths)


if __name__ == "__main__":
    unittest.main()
