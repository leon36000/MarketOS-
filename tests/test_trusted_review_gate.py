from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from tools.trusted_review_gate import (
    _fetch_reviews,
    _has_latest_exact_review,
    verify_trusted_review_gate,
)


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40


def _review(**overrides: object) -> dict[str, object]:
    verdict = str(overrides.pop("review_verdict", "APPROVE"))
    findings = overrides.pop("findings", [])
    body = (
        "MARKETOS_REVIEW_REPOSITORY=leon36000/MarketOS-\n"
        f"MARKETOS_REVIEW_BASE_SHA={BASE_SHA}\n"
        f"MARKETOS_REVIEW_HEAD_SHA={HEAD_SHA}\n"
        f"MARKETOS_REVIEW_TREE_SHA={TREE_SHA}\n"
        f"MARKETOS_REVIEW_VERDICT={verdict}\n"
        "MARKETOS_REVIEW_MODEL=GPT-5.6 Sol\n"
        "MARKETOS_REVIEW_CONTEXT=independent_blind\n"
        f"MARKETOS_REVIEW_FINDINGS_JSON={json.dumps(findings, sort_keys=True, separators=(',', ':'))}\n"
        "Trusted review evidence."
    )
    review: dict[str, object] = {
        "id": 1,
        "user": {"login": "trusted-reviewer"},
        "state": "APPROVED",
        "commit_id": HEAD_SHA,
        "body": body,
    }
    review.update(overrides)
    return review


class TrustedReviewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = patch.dict(os.environ, {"MARKETOS_TRUSTED_REVIEWERS": "trusted-reviewer"})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_trusted_exact_head_review_is_accepted(self) -> None:
        self.assertTrue(
            _has_latest_exact_review(
                [_review()],
                repository="leon36000/MarketOS-",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                pr_author="leon36000",
                trusted_reviewers={"trusted-reviewer"},
            )
        )

    def test_latest_changes_requested_review_withdraws_approval(self) -> None:
        self.assertFalse(
            _has_latest_exact_review(
                [_review(id=1), _review(id=2, state="CHANGES_REQUESTED")],
                repository="leon36000/MarketOS-",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                pr_author="leon36000",
                trusted_reviewers={"trusted-reviewer"},
            )
        )

    def test_nonblocking_verdict_rejects_high_or_malformed_findings(self) -> None:
        for findings in (
            [{"severity": "HIGH", "blocking": True, "summary": "unsafe merge"}],
            [{}],
        ):
            self.assertFalse(
                _has_latest_exact_review(
                    [_review(
                        review_verdict="APPROVE_WITH_NONBLOCKING_FINDINGS",
                        findings=findings,
                    )],
                    repository="leon36000/MarketOS-",
                    base_sha=BASE_SHA,
                    head_sha=HEAD_SHA,
                    tree_sha=TREE_SHA,
                    pr_author="leon36000",
                    trusted_reviewers={"trusted-reviewer"},
                )
            )

    def test_review_api_pagination_preserves_latest_withdrawal(self) -> None:
        first_page = [
            {
                "id": 1000 + index,
                "user": {"login": f"neutral-{index}"},
                "state": "COMMENTED",
                "commit_id": HEAD_SHA,
                "body": "neutral",
            }
            for index in range(99)
        ]
        first_page.append(_review(id=1))
        second_page = [_review(id=2, state="CHANGES_REQUESTED")]
        with patch(
            "tools.trusted_review_gate._fetch_review_page",
            side_effect=[first_page, second_page],
        ):
            reviews = _fetch_reviews("leon36000/MarketOS-", 30)
        self.assertEqual(len(reviews), 101)
        self.assertFalse(
            _has_latest_exact_review(
                reviews,
                repository="leon36000/MarketOS-",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                pr_author="leon36000",
                trusted_reviewers={"trusted-reviewer"},
            )
        )

    def test_pr_author_cannot_be_trusted_reviewer(self) -> None:
        self.assertFalse(
            _has_latest_exact_review(
                [_review(user={"login": "leon36000"})],
                repository="leon36000/MarketOS-",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                tree_sha=TREE_SHA,
                pr_author="leon36000",
                trusted_reviewers={"leon36000"},
            )
        )

    def test_empty_allowlist_fails_closed(self) -> None:
        with patch.dict(os.environ, {"MARKETOS_TRUSTED_REVIEWERS": ""}, clear=False):
            report = verify_trusted_review_gate(
                repository="leon36000/MarketOS-",
                pull_request=30,
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                pr_author="leon36000",
            )
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"], ["TRUSTED_REVIEWER_ALLOWLIST_EMPTY"])


if __name__ == "__main__":
    unittest.main()
