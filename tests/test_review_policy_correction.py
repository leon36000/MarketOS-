from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from tools.trusted_review_gate import (
    _has_latest_exact_review,
    verify_trusted_review_gate,
)


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40


def _review(**overrides: object) -> dict[str, object]:
    verdict = str(overrides.pop("review_verdict", "APPROVE"))
    findings = overrides.pop("findings", [])
    review: dict[str, object] = {
        "id": 1,
        "user": {"login": "leon36000"},
        "state": "COMMENTED",
        "commit_id": HEAD_SHA,
        "body": (
            "MARKETOS_REVIEW_REPOSITORY=leon36000/MarketOS-\n"
            f"MARKETOS_REVIEW_BASE_SHA={BASE_SHA}\n"
            f"MARKETOS_REVIEW_HEAD_SHA={HEAD_SHA}\n"
            f"MARKETOS_REVIEW_TREE_SHA={TREE_SHA}\n"
            f"MARKETOS_REVIEW_VERDICT={verdict}\n"
            "MARKETOS_REVIEW_MODEL=GPT-5.6 Sol\n"
            "MARKETOS_REVIEW_CONTEXT=independent_blind\n"
            f"MARKETOS_REVIEW_FINDINGS_JSON={json.dumps(findings, sort_keys=True, separators=(',', ':'))}\n"
            "Exact-head blind review with reproducible evidence."
        ),
    }
    review.update(overrides)
    return review


class ReviewPolicyCorrectionTests(unittest.TestCase):
    def _has_review(
        self,
        reviews: list[dict[str, object]],
        *,
        external_identity_required: bool,
        trusted_reviewers: set[str] | None = None,
    ) -> bool:
        return _has_latest_exact_review(
            reviews,
            repository="leon36000/MarketOS-",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            tree_sha=TREE_SHA,
            pr_author="leon36000",
            trusted_reviewers=trusted_reviewers or set(),
            external_identity_required=external_identity_required,
        )

    def test_ordinary_exact_sol_review_does_not_require_external_account(self) -> None:
        self.assertTrue(
            self._has_review([_review()], external_identity_required=False)
        )

    def test_ordinary_gate_passes_with_empty_allowlist_and_exact_commented_review(self) -> None:
        with (
            patch.dict(os.environ, {"MARKETOS_TRUSTED_REVIEWERS": ""}, clear=False),
            patch("tools.trusted_review_gate._fetch_tree", return_value=TREE_SHA),
            patch("tools.trusted_review_gate._fetch_reviews", return_value=[_review()]),
        ):
            report = verify_trusted_review_gate(
                repository="leon36000/MarketOS-",
                pull_request=49,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                pr_author="leon36000",
                external_identity_required=False,
            )
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["review_mode"], "SOL_EXACT_SHA")

    def test_external_mode_still_fails_closed_without_allowlist(self) -> None:
        with patch.dict(os.environ, {"MARKETOS_TRUSTED_REVIEWERS": ""}, clear=False):
            report = verify_trusted_review_gate(
                repository="leon36000/MarketOS-",
                pull_request=49,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                pr_author="leon36000",
                external_identity_required=True,
            )
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"], ["TRUSTED_REVIEWER_ALLOWLIST_EMPTY"])

    def test_external_mode_accepts_distinct_allowlisted_approval(self) -> None:
        external = _review(
            user={"login": "external-reviewer"},
            state="APPROVED",
        )
        with (
            patch.dict(
                os.environ,
                {"MARKETOS_TRUSTED_REVIEWERS": "external-reviewer"},
                clear=False,
            ),
            patch("tools.trusted_review_gate._fetch_tree", return_value=TREE_SHA),
            patch("tools.trusted_review_gate._fetch_reviews", return_value=[external]),
        ):
            report = verify_trusted_review_gate(
                repository="leon36000/MarketOS-",
                pull_request=49,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                pr_author="leon36000",
                external_identity_required=True,
            )
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["review_mode"], "EXTERNAL_EXACT_SHA")

    def test_latest_changes_requested_withdraws_ordinary_review(self) -> None:
        self.assertFalse(
            self._has_review(
                [
                    _review(id=1, submitted_at="2026-08-26T16:00:00Z"),
                    _review(
                        id=2,
                        state="CHANGES_REQUESTED",
                        submitted_at="2026-08-26T16:01:00Z",
                    ),
                ],
                external_identity_required=False,
            )
        )

    def test_blocking_findings_never_pass_as_nonblocking(self) -> None:
        self.assertFalse(
            self._has_review(
                [
                    _review(
                        review_verdict="APPROVE_WITH_NONBLOCKING_FINDINGS",
                        findings=[
                            {
                                "severity": "HIGH",
                                "blocking": True,
                                "summary": "unsafe",
                            }
                        ],
                    )
                ],
                external_identity_required=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
