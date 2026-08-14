"""Independent, evidence-bound and shadow-only research promotion.

The strongest state in this module is eligibility for an independently
controlled shadow evaluation.  There is deliberately no LIVE state, no champion
activation and no claim that diagnostics establish predictive edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .experiments import (
    DatasetPartition,
    DatasetRole,
    ExperimentLedger,
    TrialStatus,
)
from .validation import BaselineKind, FidelityStage, ValidationEvidence

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _optional_text(value: str | None, code: str) -> str | None:
    if value is None:
        return None
    return _text(value, code)


def _positive_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvariantViolation(code)
    return value


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _sha256(value: str, code: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise InvariantViolation(code)
    return value


def _findings(values: Iterable[str], code: str) -> tuple[str, ...]:
    materialized = tuple(_text(value, code) for value in values)
    if len(materialized) != len(set(materialized)):
        raise InvariantViolation(f"DUPLICATE_{code}")
    return materialized


def _reason_code(exc: Exception) -> str:
    text = str(exc).strip()
    return text.split(":", 1)[0] if text else type(exc).__name__


class PromotionState(str, Enum):
    BLOCKED = "BLOCKED"
    ELIGIBLE_FOR_SHADOW = "ELIGIBLE_FOR_SHADOW"


@dataclass(frozen=True, slots=True)
class IndependentReview:
    review_id: str
    reviewer_id: str
    reviewer_role: DatasetRole
    evidence_sha256: str
    approved: bool
    human_approval_id: str | None
    minority_findings: tuple[str, ...]
    unresolved_findings: tuple[str, ...]
    reviewed_at_ns: int
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "review_id", _text(self.review_id, "INVALID_REVIEW_ID"))
        object.__setattr__(
            self,
            "reviewer_id",
            _text(self.reviewer_id, "INVALID_REVIEWER_ID"),
        )
        if not isinstance(self.reviewer_role, DatasetRole):
            raise InvariantViolation("INVALID_REVIEWER_ROLE")
        _sha256(self.evidence_sha256, "INVALID_REVIEW_EVIDENCE_SHA256")
        if not isinstance(self.approved, bool):
            raise InvariantViolation("INVALID_REVIEW_APPROVAL")
        object.__setattr__(
            self,
            "human_approval_id",
            _optional_text(
                self.human_approval_id,
                "INVALID_HUMAN_APPROVAL_ID",
            ),
        )
        object.__setattr__(
            self,
            "minority_findings",
            _findings(self.minority_findings, "MINORITY_FINDING"),
        )
        object.__setattr__(
            self,
            "unresolved_findings",
            _findings(self.unresolved_findings, "UNRESOLVED_REVIEW_FINDING"),
        )
        _nonnegative_int(self.reviewed_at_ns, "INVALID_REVIEW_TIME")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("REVIEW_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_role": self.reviewer_role,
            "evidence_sha256": self.evidence_sha256,
            "approved": self.approved,
            "human_approval_id": self.human_approval_id,
            "minority_findings": self.minority_findings,
            "unresolved_findings": self.unresolved_findings,
            "reviewed_at_ns": self.reviewed_at_ns,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def assert_integrity(self) -> None:
        IndependentReview(
            review_id=self.review_id,
            reviewer_id=self.reviewer_id,
            reviewer_role=self.reviewer_role,
            evidence_sha256=self.evidence_sha256,
            approved=self.approved,
            human_approval_id=self.human_approval_id,
            minority_findings=self.minority_findings,
            unresolved_findings=self.unresolved_findings,
            reviewed_at_ns=self.reviewed_at_ns,
            live_trading_state=self.live_trading_state,
        )


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    request_id: str
    candidate_trial_id: str
    search_id: str
    strategy_id: str
    strategy_version: int
    requested_by_id: str
    requested_by_role: DatasetRole
    validation_evidence_sha256: str
    independent_review: IndependentReview
    rollback_plan: str | None
    unresolved_assumption_breaks: tuple[str, ...]
    requested_at_ns: int
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        for field, code in (
            ("request_id", "INVALID_PROMOTION_REQUEST_ID"),
            ("candidate_trial_id", "INVALID_CANDIDATE_TRIAL_ID"),
            ("search_id", "INVALID_PROMOTION_SEARCH_ID"),
            ("strategy_id", "INVALID_PROMOTION_STRATEGY_ID"),
            ("requested_by_id", "INVALID_PROMOTION_REQUESTER_ID"),
        ):
            object.__setattr__(self, field, _text(getattr(self, field), code))
        _positive_int(self.strategy_version, "INVALID_STRATEGY_VERSION")
        if not isinstance(self.requested_by_role, DatasetRole):
            raise InvariantViolation("INVALID_PROMOTION_REQUESTER_ROLE")
        _sha256(
            self.validation_evidence_sha256,
            "INVALID_VALIDATION_EVIDENCE_SHA256",
        )
        if not isinstance(self.independent_review, IndependentReview):
            raise InvariantViolation("INDEPENDENT_REVIEW_REQUIRED")
        object.__setattr__(
            self,
            "rollback_plan",
            _optional_text(self.rollback_plan, "INVALID_ROLLBACK_PLAN"),
        )
        object.__setattr__(
            self,
            "unresolved_assumption_breaks",
            _findings(
                self.unresolved_assumption_breaks,
                "UNRESOLVED_ASSUMPTION_BREAK",
            ),
        )
        _nonnegative_int(self.requested_at_ns, "INVALID_PROMOTION_REQUEST_TIME")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("PROMOTION_REQUEST_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "candidate_trial_id": self.candidate_trial_id,
            "search_id": self.search_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "requested_by_id": self.requested_by_id,
            "requested_by_role": self.requested_by_role,
            "validation_evidence_sha256": self.validation_evidence_sha256,
            "independent_review": self.independent_review,
            "rollback_plan": self.rollback_plan,
            "unresolved_assumption_breaks": self.unresolved_assumption_breaks,
            "requested_at_ns": self.requested_at_ns,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def assert_integrity(self) -> None:
        self.independent_review.assert_integrity()
        PromotionRequest(
            request_id=self.request_id,
            candidate_trial_id=self.candidate_trial_id,
            search_id=self.search_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            requested_by_id=self.requested_by_id,
            requested_by_role=self.requested_by_role,
            validation_evidence_sha256=(
                self.validation_evidence_sha256
            ),
            independent_review=self.independent_review,
            rollback_plan=self.rollback_plan,
            unresolved_assumption_breaks=(
                self.unresolved_assumption_breaks
            ),
            requested_at_ns=self.requested_at_ns,
            live_trading_state=self.live_trading_state,
        )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    state: PromotionState
    request_id: str
    candidate_trial_id: str
    reasons: tuple[str, ...]
    request_sha256: str
    evidence_sha256: str
    review_sha256: str
    trial_population_sha256: str
    decision_sha256: str
    champion_promoted: bool = False
    strategy_edge_proven: bool = False
    profitability_state: str = "UNPROVEN"
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        if not isinstance(self.state, PromotionState):
            raise InvariantViolation("INVALID_PROMOTION_STATE")
        object.__setattr__(
            self,
            "request_id",
            _text(self.request_id, "INVALID_PROMOTION_REQUEST_ID"),
        )
        object.__setattr__(
            self,
            "candidate_trial_id",
            _text(self.candidate_trial_id, "INVALID_CANDIDATE_TRIAL_ID"),
        )
        reasons = tuple(self.reasons)
        if len(reasons) != len(set(reasons)):
            raise InvariantViolation("DUPLICATE_PROMOTION_REASON")
        object.__setattr__(self, "reasons", reasons)
        for digest, code in (
            (self.request_sha256, "INVALID_PROMOTION_REQUEST_SHA256"),
            (self.evidence_sha256, "INVALID_PROMOTION_EVIDENCE_SHA256"),
            (self.review_sha256, "INVALID_PROMOTION_REVIEW_SHA256"),
            (
                self.trial_population_sha256,
                "INVALID_PROMOTION_TRIAL_POPULATION_SHA256",
            ),
            (self.decision_sha256, "INVALID_PROMOTION_DECISION_SHA256"),
        ):
            _sha256(digest, code)
        if self.state is PromotionState.ELIGIBLE_FOR_SHADOW and reasons:
            raise InvariantViolation("ELIGIBLE_PROMOTION_HAS_REASONS")
        if self.state is PromotionState.BLOCKED and not reasons:
            raise InvariantViolation("BLOCKED_PROMOTION_REQUIRES_REASON")
        if self.champion_promoted is not False:
            raise InvariantViolation("CHAMPION_PROMOTION_FORBIDDEN")
        if self.strategy_edge_proven is not False:
            raise InvariantViolation("PROMOTION_CANNOT_PROVE_EDGE")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("PROMOTION_CANNOT_PROVE_PROFITABILITY")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("PROMOTION_CANNOT_CHANGE_LIVE_LOCK")
        if self.decision_sha256 != self.recomputed_sha256():
            raise InvariantViolation("PROMOTION_DECISION_SHA256_MISMATCH")

    def canonical_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "state": self.state,
            "request_id": self.request_id,
            "candidate_trial_id": self.candidate_trial_id,
            "reasons": self.reasons,
            "request_sha256": self.request_sha256,
            "evidence_sha256": self.evidence_sha256,
            "review_sha256": self.review_sha256,
            "trial_population_sha256": self.trial_population_sha256,
            "champion_promoted": self.champion_promoted,
            "strategy_edge_proven": self.strategy_edge_proven,
            "profitability_state": self.profitability_state,
            "live_trading_state": self.live_trading_state,
        }
        if include_hash:
            value["decision_sha256"] = self.decision_sha256
        return value

    def recomputed_sha256(self) -> str:
        return canonical_sha256(self.canonical_dict(include_hash=False))


class PromotionGate:
    """Deterministic fail-closed gate whose ceiling is shadow eligibility."""

    live_trading_state = "HARD_LOCKED"
    champion_promoted = False
    strategy_edge_proven = False

    @staticmethod
    def _append_reason(reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    def evaluate(
        self,
        request: PromotionRequest,
        evidence: ValidationEvidence,
        ledger: ExperimentLedger,
    ) -> PromotionDecision:
        reasons: list[str] = []
        review = request.independent_review
        for integrity_check in (
            request.assert_integrity,
            review.assert_integrity,
            evidence.assert_integrity,
        ):
            try:
                integrity_check()
            except InvariantViolation as exc:
                self._append_reason(reasons, _reason_code(exc))
        evidence_sha256 = evidence.sha256()
        trials = ledger.trials(search_id=request.search_id)
        trial_population_sha256 = canonical_sha256(
            tuple(trial.sha256() for trial in trials)
        )

        if request.validation_evidence_sha256 != evidence_sha256:
            self._append_reason(reasons, "VALIDATION_EVIDENCE_MISMATCH")
        if review.evidence_sha256 != evidence_sha256:
            self._append_reason(reasons, "REVIEW_EVIDENCE_MISMATCH")
        if (
            evidence.search_id != request.search_id
            or evidence.strategy_id != request.strategy_id
            or evidence.strategy_version != request.strategy_version
        ):
            self._append_reason(reasons, "PROMOTION_EVIDENCE_SCOPE_MISMATCH")

        candidate = next(
            (
                trial
                for trial in trials
                if trial.trial_id == request.candidate_trial_id
            ),
            None,
        )
        if candidate is None:
            self._append_reason(reasons, "CANDIDATE_TRIAL_NOT_FOUND")
        elif candidate.status is not TrialStatus.SUCCEEDED:
            self._append_reason(reasons, "CANDIDATE_TRIAL_NOT_SUCCESSFUL")

        try:
            evidence.validate_against_trials(trials)
        except InvariantViolation as exc:
            self._append_reason(reasons, _reason_code(exc))

        if len(tuple(evidence.fold_ids)) < 2:
            self._append_reason(reasons, "MULTIPLE_FOLDS_REQUIRED")
        if evidence.purging_applied is not True:
            self._append_reason(reasons, "PURGING_REQUIRED")
        if (
            isinstance(evidence.embargo_ns, bool)
            or not isinstance(evidence.embargo_ns, int)
            or evidence.embargo_ns <= 0
        ):
            self._append_reason(reasons, "EMBARGO_REQUIRED")
        if BaselineKind.NO_TRADE not in tuple(evidence.baseline_kinds):
            self._append_reason(reasons, "NO_TRADE_BASELINE_REQUIRED")
        if not any(
            baseline is not BaselineKind.NO_TRADE
            for baseline in tuple(evidence.baseline_kinds)
        ):
            self._append_reason(reasons, "SIMPLE_BASELINE_REQUIRED")
        if evidence.cost_distribution is None:
            self._append_reason(reasons, "COST_DISTRIBUTION_REQUIRED")
        if evidence.capacity_distribution is None:
            self._append_reason(reasons, "CAPACITY_DISTRIBUTION_REQUIRED")
        if evidence.fill_uncertainty_distribution is None:
            self._append_reason(
                reasons,
                "FILL_UNCERTAINTY_DISTRIBUTION_REQUIRED",
            )
        if evidence.synthetic_only:
            self._append_reason(reasons, "SYNTHETIC_ONLY_EVIDENCE")
        if FidelityStage.EVENT_REPLAY not in tuple(
            evidence.completed_fidelity_stages
        ):
            self._append_reason(reasons, "EVENT_REPLAY_REQUIRED")

        for receipt in ledger.access_receipts():
            if (
                receipt.partition is DatasetPartition.HIDDEN_HOLDOUT
                and receipt.allowed
                and (
                    receipt.role is not DatasetRole.INDEPENDENT_EVALUATOR
                    or receipt.purpose != "FINAL_EVALUATION"
                )
            ):
                self._append_reason(reasons, "HIDDEN_HOLDOUT_VIOLATION")

        if review.reviewer_role is not DatasetRole.INDEPENDENT_EVALUATOR:
            self._append_reason(reasons, "INDEPENDENT_REVIEW_REQUIRED")
        if review.reviewer_id == request.requested_by_id:
            self._append_reason(reasons, "SELF_PROMOTION_FORBIDDEN")
        if not review.approved:
            self._append_reason(reasons, "INDEPENDENT_APPROVAL_REQUIRED")
        if review.human_approval_id is None:
            self._append_reason(reasons, "HUMAN_APPROVAL_REQUIRED")
        if not review.minority_findings:
            self._append_reason(reasons, "MINORITY_FINDINGS_REQUIRED")
        if review.unresolved_findings:
            self._append_reason(reasons, "UNRESOLVED_REVIEW_FINDINGS")
        if request.rollback_plan is None:
            self._append_reason(reasons, "ROLLBACK_PLAN_REQUIRED")
        if request.unresolved_assumption_breaks:
            self._append_reason(reasons, "UNRESOLVED_ASSUMPTION_BREAKS")
        if review.reviewed_at_ns < evidence.created_at_ns:
            self._append_reason(reasons, "REVIEW_BEFORE_EVIDENCE")
        if request.requested_at_ns < review.reviewed_at_ns:
            self._append_reason(reasons, "REQUEST_BEFORE_REVIEW")

        state = (
            PromotionState.BLOCKED
            if reasons
            else PromotionState.ELIGIBLE_FOR_SHADOW
        )
        payload = {
            "state": state,
            "request_id": request.request_id,
            "candidate_trial_id": request.candidate_trial_id,
            "reasons": tuple(reasons),
            "request_sha256": request.sha256(),
            "evidence_sha256": evidence_sha256,
            "review_sha256": review.sha256(),
            "trial_population_sha256": trial_population_sha256,
            "champion_promoted": False,
            "strategy_edge_proven": False,
            "profitability_state": "UNPROVEN",
            "live_trading_state": "HARD_LOCKED",
        }
        return PromotionDecision(
            state=state,
            request_id=request.request_id,
            candidate_trial_id=request.candidate_trial_id,
            reasons=tuple(reasons),
            request_sha256=request.sha256(),
            evidence_sha256=evidence_sha256,
            review_sha256=review.sha256(),
            trial_population_sha256=trial_population_sha256,
            decision_sha256=canonical_sha256(payload),
        )
