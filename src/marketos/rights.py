"""Fail-closed data-rights contracts.

Unknown capabilities are denied.  A policy is accepted only when every field in
the C2 rights surface has an explicit decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .canonical import canonical_sha256
from .errors import InvariantViolation


REQUIRED_RIGHTS_FIELDS = frozenset(
    {
        "display",
        "non_display",
        "professional_status",
        "users",
        "devices",
        "servers",
        "sites",
        "applications",
        "storage",
        "retention_period",
        "historical_replay",
        "derived_data",
        "cloud_processing",
        "cloud_regions",
        "redistribution",
        "model_training",
        "embeddings",
        "model_output_use",
        "audit_reporting",
        "termination_deletion",
        "exit_export",
    }
)


class RightDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RightsPolicy:
    policy_id: str
    fields: Mapping[str, RightDecision]
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise InvariantViolation("MISSING_RIGHTS_POLICY_ID")
        if set(self.fields) != REQUIRED_RIGHTS_FIELDS:
            missing = sorted(REQUIRED_RIGHTS_FIELDS - set(self.fields))
            extra = sorted(set(self.fields) - REQUIRED_RIGHTS_FIELDS)
            raise InvariantViolation(
                f"INCOMPLETE_RIGHTS_POLICY:missing={missing}:extra={extra}"
            )
        normalized: dict[str, RightDecision] = {}
        for field, decision in self.fields.items():
            if not isinstance(decision, RightDecision):
                raise InvariantViolation(f"INVALID_RIGHT_DECISION:{field}")
            normalized[field] = decision
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("RIGHTS_POLICY_CANNOT_CHANGE_LIVE_LOCK")
        object.__setattr__(self, "fields", MappingProxyType(dict(sorted(normalized.items()))))

    def decision(self, capability: str) -> RightDecision:
        return self.fields.get(capability, RightDecision.UNKNOWN)

    def allows(self, capability: str) -> bool:
        return self.decision(capability) is RightDecision.ALLOW

    def canonical_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "fields": self.fields,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())
