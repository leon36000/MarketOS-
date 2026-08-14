from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
import unittest

from marketos.experiments import (
    AccessDecision,
    AccessReceipt,
    DatasetAccessPolicy,
    DatasetPartition,
    DatasetRole,
    ExperimentLedger,
    SearchPlan,
    StrategyDefinition,
    TrialRecord,
    TrialStatus,
)
from marketos.promotion import (
    IndependentReview,
    PromotionGate,
    PromotionRequest,
    PromotionState,
)
from marketos.validation import (
    BaselineKind,
    FidelityStage,
    MetricDistribution,
    MultipleTestingEvidence,
    ValidationEvidence,
)


class PromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-promotion-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.ledger = ExperimentLedger(self.temp / "experiments.sqlite")
        self.addCleanup(self.ledger.close)
        self.strategy = StrategyDefinition(
            strategy_id="reversal-liquidity",
            version=1,
            hypothesis="Falsifiable liquidity-shock reversal",
            mechanism="Temporary imbalance mean-reverts after forced flow",
            universe=("AAPL@XNAS", "MSFT@XNAS"),
            features=("spread-z@1", "signed-volume@1"),
            decision_rule="BUY only after threshold and all abstention checks",
            position_rule="risk-scaled capped long-only position",
            risk_budget={"gross_fraction": Decimal("0.10")},
            execution_policy="passive-first; cancel on stale quote",
            abstention="stale data, halt, crossed market, missing state",
            failure_modes=("information event", "cost regime break"),
            data_cutoffs={
                "features_available_at_ns": 1_000,
                "model_available_at_ns": 1_000,
                "memory_available_at_ns": 1_000,
                "prompt_available_at_ns": 1_000,
            },
            code_sha256="a" * 64,
            config_sha256="b" * 64,
        )
        self.plan = SearchPlan(
            search_id="search-reversal-001",
            version=1,
            strategy_id=self.strategy.strategy_id,
            strategy_version=self.strategy.version,
            objective_metric="DEFLATED_SHARPE",
            parameter_space={"threshold": (Decimal("1.5"), Decimal("2.0"))},
            seeds=(7, 11, 19),
            max_trials=3,
            created_at_ns=1_100,
            hidden_holdout_id="holdout-2026-final",
        )
        self.trials = (
            self.trial("trial-success", 1, TrialStatus.SUCCEEDED, metric="0.30"),
            self.trial(
                "trial-failed",
                2,
                TrialStatus.FAILED,
                failure_reason="numerical instability",
            ),
            self.trial(
                "trial-abandoned",
                3,
                TrialStatus.ABANDONED,
                failure_reason="search budget exhausted",
            ),
        )
        self.ledger.append_strategy(self.strategy)
        self.ledger.append_search_plan(self.plan)
        for trial in self.trials:
            self.ledger.append_trial(trial)
        self.evidence = self.validation_evidence()
        self.gate = PromotionGate()

    @staticmethod
    def distribution(unit: str, p05: str, p50: str, p95: str) -> MetricDistribution:
        return MetricDistribution(
            unit=unit,
            p05=Decimal(p05),
            p50=Decimal(p50),
            p95=Decimal(p95),
            sample_count=100,
        )

    def trial(
        self,
        trial_id: str,
        ordinal: int,
        status: TrialStatus,
        *,
        metric: str | None = None,
        failure_reason: str | None = None,
    ) -> TrialRecord:
        return TrialRecord(
            trial_id=trial_id,
            search_id="search-reversal-001",
            strategy_id="reversal-liquidity",
            strategy_version=1,
            ordinal=ordinal,
            parameters={
                "threshold": (
                    Decimal("1.5"),
                    Decimal("2.0"),
                    Decimal("1.5"),
                )[ordinal - 1]
            },
            seed=(7, 11, 19)[ordinal - 1],
            status=status,
            started_at_ns=2_000 + ordinal * 10,
            completed_at_ns=2_005 + ordinal * 10,
            data_cutoff_ns=1_900,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            metrics=(
                {}
                if metric is None
                else {"deflated_sharpe": Decimal(metric)}
            ),
            failure_reason=failure_reason,
        )

    def validation_evidence(self, **overrides) -> ValidationEvidence:
        trial_ids = tuple(trial.trial_id for trial in self.trials)
        values = dict(
            evidence_id="validation-reversal-001",
            search_id="search-reversal-001",
            strategy_id="reversal-liquidity",
            strategy_version=1,
            split_plan_sha256="c" * 64,
            fold_ids=("fold-0001", "fold-0002"),
            purging_applied=True,
            embargo_ns=10,
            baseline_kinds=(BaselineKind.NO_TRADE, BaselineKind.BUY_AND_HOLD),
            multiple_testing=MultipleTestingEvidence(
                tried_trial_ids=trial_ids,
                pbo_trial_ids=trial_ids,
                deflated_sharpe_trial_ids=trial_ids,
                cscv_fold_count=8,
                pbo_probability=Decimal("0.25"),
                deflated_sharpe=Decimal("0.30"),
            ),
            cost_distribution=self.distribution("BPS", "1", "3", "8"),
            capacity_distribution=self.distribution(
                "USD_NOTIONAL", "100000", "500000", "1000000"
            ),
            fill_uncertainty_distribution=self.distribution(
                "FILL_RATIO", "0.40", "0.75", "0.95"
            ),
            completed_fidelity_stages=(
                FidelityStage.SYNTHETIC,
                FidelityStage.BAR_REPLAY,
                FidelityStage.EVENT_REPLAY,
            ),
            claimed_fidelity_stage=FidelityStage.EVENT_REPLAY,
            synthetic_only=False,
            created_at_ns=5_000,
        )
        values.update(overrides)
        return ValidationEvidence(**values)

    def review(self, evidence: ValidationEvidence | None = None, **overrides) -> IndependentReview:
        evidence = self.evidence if evidence is None else evidence
        values = dict(
            review_id="review-001",
            reviewer_id="human-risk-reviewer",
            reviewer_role=DatasetRole.INDEPENDENT_EVALUATOR,
            evidence_sha256=evidence.sha256(),
            approved=True,
            human_approval_id="human-approval-001",
            minority_findings=(
                "capacity remains sensitive to stressed participation limits",
            ),
            unresolved_findings=(),
            reviewed_at_ns=6_000,
        )
        values.update(overrides)
        return IndependentReview(**values)

    def request(self, evidence: ValidationEvidence | None = None, **overrides) -> PromotionRequest:
        evidence = self.evidence if evidence is None else evidence
        values = dict(
            request_id="promotion-001",
            candidate_trial_id="trial-success",
            search_id="search-reversal-001",
            strategy_id="reversal-liquidity",
            strategy_version=1,
            requested_by_id="research-orchestrator",
            requested_by_role=DatasetRole.MODEL_COUNCIL,
            validation_evidence_sha256=evidence.sha256(),
            independent_review=self.review(evidence),
            rollback_plan="Disable candidate, preserve evidence, revert to NO_TRADE",
            unresolved_assumption_breaks=(),
            requested_at_ns=6_100,
        )
        values.update(overrides)
        return PromotionRequest(**values)

    def assert_blocked(
        self,
        reason: str,
        *,
        evidence: ValidationEvidence | None = None,
        request: PromotionRequest | None = None,
    ) -> None:
        evidence = self.evidence if evidence is None else evidence
        request = self.request(evidence) if request is None else request
        decision = self.gate.evaluate(request, evidence, self.ledger)
        self.assertEqual(decision.state, PromotionState.BLOCKED)
        self.assertIn(reason, decision.reasons)
        self.assertFalse(decision.champion_promoted)
        self.assertEqual(decision.live_trading_state, "HARD_LOCKED")

    def test_complete_independent_review_can_only_grant_shadow_eligibility(self) -> None:
        decision = self.gate.evaluate(
            self.request(),
            self.evidence,
            self.ledger,
        )
        self.assertEqual(decision.state, PromotionState.ELIGIBLE_FOR_SHADOW)
        self.assertEqual(decision.reasons, ())
        self.assertFalse(decision.champion_promoted)
        self.assertFalse(decision.strategy_edge_proven)
        self.assertEqual(decision.profitability_state, "UNPROVEN")
        self.assertEqual(decision.live_trading_state, "HARD_LOCKED")
        self.assertEqual(decision.decision_sha256, decision.recomputed_sha256())

    def test_live_promotion_state_does_not_exist(self) -> None:
        with self.assertRaises(ValueError):
            PromotionState("LIVE")

    def test_synthetic_only_or_incomplete_fidelity_is_blocked(self) -> None:
        synthetic = self.validation_evidence(
            completed_fidelity_stages=(FidelityStage.SYNTHETIC,),
            claimed_fidelity_stage=FidelityStage.SYNTHETIC,
            synthetic_only=True,
        )
        self.assert_blocked("SYNTHETIC_ONLY_EVIDENCE", evidence=synthetic)
        incomplete = self.validation_evidence(
            completed_fidelity_stages=(
                FidelityStage.SYNTHETIC,
                FidelityStage.BAR_REPLAY,
            ),
            claimed_fidelity_stage=FidelityStage.BAR_REPLAY,
        )
        self.assert_blocked("EVENT_REPLAY_REQUIRED", evidence=incomplete)

    def test_missing_baseline_purge_embargo_or_multiple_folds_is_blocked(self) -> None:
        cases = (
            ("NO_TRADE_BASELINE_REQUIRED", "baseline_kinds", (BaselineKind.BUY_AND_HOLD,)),
            ("MULTIPLE_FOLDS_REQUIRED", "fold_ids", ("fold-0001",)),
            ("PURGING_REQUIRED", "purging_applied", False),
            ("EMBARGO_REQUIRED", "embargo_ns", 0),
        )
        for reason, field, value in cases:
            with self.subTest(reason=reason):
                evidence = self.validation_evidence()
                object.__setattr__(evidence, field, value)
                self.assert_blocked(reason, evidence=evidence)

    def test_missing_cost_capacity_or_fill_distribution_is_blocked(self) -> None:
        cases = (
            ("COST_DISTRIBUTION_REQUIRED", "cost_distribution"),
            ("CAPACITY_DISTRIBUTION_REQUIRED", "capacity_distribution"),
            ("FILL_UNCERTAINTY_DISTRIBUTION_REQUIRED", "fill_uncertainty_distribution"),
        )
        for reason, field in cases:
            with self.subTest(reason=reason):
                evidence = self.validation_evidence()
                object.__setattr__(evidence, field, None)
                self.assert_blocked(reason, evidence=evidence)

    def test_incomplete_trial_population_is_blocked(self) -> None:
        evidence = self.validation_evidence()
        object.__setattr__(
            evidence.multiple_testing,
            "tried_trial_ids",
            ("trial-success",),
        )
        self.assert_blocked("TRIED_TRIAL_POPULATION_MISMATCH", evidence=evidence)

    def test_unauthorized_successful_hidden_holdout_access_is_blocked(self) -> None:
        policy = DatasetAccessPolicy(
            policy_id="access-v1",
            version=1,
            hidden_holdout_id="holdout-2026-final",
        )
        forged = AccessDecision(
            role=DatasetRole.OPTIMIZER,
            partition=DatasetPartition.HIDDEN_HOLDOUT,
            purpose="OPTIMIZATION",
            requested_at_ns=4_000,
            allowed=True,
            reason="FORGED_ALLOW",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            hidden_holdout_id=policy.hidden_holdout_id,
            policy_sha256=policy.sha256(),
        )
        self.ledger.append_access_receipt(
            AccessReceipt.from_decision(
                receipt_id="unauthorized-holdout",
                decision=forged,
            )
        )
        self.assert_blocked("HIDDEN_HOLDOUT_VIOLATION")

    def test_denied_holdout_attempt_is_audited_but_does_not_block(self) -> None:
        policy = DatasetAccessPolicy(
            policy_id="access-v1",
            version=1,
            hidden_holdout_id="holdout-2026-final",
        )
        denied = policy.authorize(
            role=DatasetRole.OPTIMIZER,
            partition=DatasetPartition.HIDDEN_HOLDOUT,
            purpose="OPTIMIZATION",
            requested_at_ns=4_000,
        )
        self.ledger.append_access_receipt(
            AccessReceipt.from_decision(
                receipt_id="denied-holdout",
                decision=denied,
            )
        )
        decision = self.gate.evaluate(self.request(), self.evidence, self.ledger)
        self.assertEqual(decision.state, PromotionState.ELIGIBLE_FOR_SHADOW)

    def test_candidate_or_model_council_cannot_self_approve(self) -> None:
        for role in (
            DatasetRole.CANDIDATE_GENERATOR,
            DatasetRole.MODEL_COUNCIL,
        ):
            with self.subTest(role=role):
                review = self.review(
                    reviewer_id="research-orchestrator",
                    reviewer_role=role,
                )
                request = self.request(independent_review=review)
                self.assert_blocked("INDEPENDENT_REVIEW_REQUIRED", request=request)
                decision = self.gate.evaluate(request, self.evidence, self.ledger)
                self.assertIn("SELF_PROMOTION_FORBIDDEN", decision.reasons)

    def test_review_must_bind_evidence_and_include_human_approval_minority_and_rollback(self) -> None:
        cases = (
            (
                "REVIEW_EVIDENCE_MISMATCH",
                self.request(
                    independent_review=self.review(evidence_sha256="f" * 64)
                ),
            ),
            (
                "HUMAN_APPROVAL_REQUIRED",
                self.request(
                    independent_review=self.review(human_approval_id=None)
                ),
            ),
            (
                "MINORITY_FINDINGS_REQUIRED",
                self.request(
                    independent_review=self.review(minority_findings=())
                ),
            ),
            (
                "ROLLBACK_PLAN_REQUIRED",
                self.request(rollback_plan=None),
            ),
        )
        for reason, request in cases:
            with self.subTest(reason=reason):
                self.assert_blocked(reason, request=request)

    def test_unresolved_findings_or_assumption_breaks_block_promotion(self) -> None:
        request = self.request(
            independent_review=self.review(
                unresolved_findings=("event replay mismatch",)
            )
        )
        self.assert_blocked("UNRESOLVED_REVIEW_FINDINGS", request=request)
        request = self.request(
            unresolved_assumption_breaks=("liquidity regime changed",)
        )
        self.assert_blocked("UNRESOLVED_ASSUMPTION_BREAKS", request=request)

    def test_failed_or_unknown_candidate_trial_is_blocked(self) -> None:
        self.assert_blocked(
            "CANDIDATE_TRIAL_NOT_SUCCESSFUL",
            request=self.request(candidate_trial_id="trial-failed"),
        )
        self.assert_blocked(
            "CANDIDATE_TRIAL_NOT_FOUND",
            request=self.request(candidate_trial_id="missing-trial"),
        )

    def test_request_evidence_hash_mismatch_is_blocked(self) -> None:
        self.assert_blocked(
            "VALIDATION_EVIDENCE_MISMATCH",
            request=self.request(validation_evidence_sha256="f" * 64),
        )


if __name__ == "__main__":
    unittest.main()
