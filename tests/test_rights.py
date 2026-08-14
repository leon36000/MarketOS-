from __future__ import annotations

import unittest

from marketos.errors import InvariantViolation
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy


class RightsPolicyTests(unittest.TestCase):
    def complete_fields(self) -> dict[str, RightDecision]:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        fields.update(
            {
                "storage": RightDecision.ALLOW,
                "historical_replay": RightDecision.ALLOW,
                "derived_data": RightDecision.ALLOW,
                "audit_reporting": RightDecision.ALLOW,
            }
        )
        return fields

    def test_complete_policy_allows_only_explicit_allow(self) -> None:
        policy = RightsPolicy("policy-1", self.complete_fields())
        self.assertTrue(policy.allows("storage"))
        self.assertFalse(policy.allows("model_training"))
        self.assertFalse(policy.allows("not-a-right"))
        self.assertEqual(policy.decision("not-a-right"), RightDecision.UNKNOWN)
        self.assertEqual(policy.live_trading_state, "HARD_LOCKED")

    def test_missing_or_extra_rights_fields_fail_closed(self) -> None:
        fields = self.complete_fields()
        fields.pop("storage")
        with self.assertRaisesRegex(InvariantViolation, "INCOMPLETE_RIGHTS_POLICY"):
            RightsPolicy("policy-1", fields)
        fields = self.complete_fields()
        fields["invented"] = RightDecision.ALLOW
        with self.assertRaisesRegex(InvariantViolation, "INCOMPLETE_RIGHTS_POLICY"):
            RightsPolicy("policy-1", fields)

    def test_policy_is_immutable_and_hash_stable(self) -> None:
        policy = RightsPolicy("policy-1", self.complete_fields())
        with self.assertRaises(TypeError):
            policy.fields["storage"] = RightDecision.DENY
        self.assertEqual(policy.sha256(), policy.sha256())


if __name__ == "__main__":
    unittest.main()
