from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
import unittest

from marketos.errors import InvariantViolation
from marketos.experiments import (
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
    TemporalSample,
    ValidationEvidence,
    WalkForwardConfig,
    build_purged_walk_forward_plan,
)


class ResearchGovernanceAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-research-hardening-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.ledger = ExperimentLedger(self.temp / "experiments.sqlite")
        self.addCleanup(self.ledger.close)
        self.strategy = StrategyDefinition(
            strategy_id="budgeted-search",
            version=1,
            hypothesis="Falsifiable hypothesis",
            mechanism="Declared mechanism",
            universe=("AAPL@XNAS",),
            features=("spread-z@1",),
            decision_rule="Declared decision rule",
            position_rule="Declared position rule",
            risk_budget={"gross_fraction": Decimal("0.10")},
            execution_policy="Declared execution policy",
            abstention="Abstain on invalid state",
            failure_modes=("regime break",),
            data_cutoffs={
                "features_available_at_ns": 100,
                "model_available_at_ns": 100,
                "memory_available_at_ns": 100,
                "prompt_available_at_ns": 100,
            },
            code_sha256="a" * 64,
            config_sha256="b" * 64,
        )
        self.plan = SearchPlan(
            search_id="budgeted-search-001",
            version=1,
            strategy_id=self.strategy.strategy_id,
            strategy_version=self.strategy.version,
            objective_metric="DEFLATED_SHARPE",
            parameter_space={
                "threshold": (Decimal("1.5"), Decimal("2.0")),
                "holding_bars": (1, 2),
            },
            seeds=(7, 11),
            max_trials=2,
            created_at_ns=200,
            hidden_holdout_id="holdout-final",
        )
        self.ledger.append_strategy(self.strategy)
        self.ledger.append_search_plan(self.plan)

    def trial(
        self,
        trial_id: str,
        ordinal: int,
        *,
        seed: int = 7,
        parameters: dict[str, object] | None = None,
    ) -> TrialRecord:
        return TrialRecord(
            trial_id=trial_id,
            search_id=self.plan.search_id,
            strategy_id=self.strategy.strategy_id,
            strategy_version=self.strategy.version,
            ordinal=ordinal,
            parameters=(
                {"threshold": Decimal("1.5"), "holding_bars": 1}
                if parameters is None
                else parameters
            ),
            seed=seed,
            status=TrialStatus.SUCCEEDED,
            started_at_ns=300 + ordinal * 10,
            completed_at_ns=305 + ordinal * 10,
            data_cutoff_ns=250,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            metrics={"deflated_sharpe": Decimal("0.10")},
            failure_reason=None,
        )

    @staticmethod
    def distribution(unit: str) -> MetricDistribution:
        return MetricDistribution(
            unit=unit,
            p05=Decimal("1"),
            p50=Decimal("2"),
            p95=Decimal("3"),
            sample_count=20,
        )

    def validation_fixture(self) -> tuple[tuple[TrialRecord, ...], ValidationEvidence]:
        trials = (
            self.trial("trial-1", 1, seed=7),
            self.trial(
                "trial-2",
                2,
                seed=11,
                parameters={"threshold": Decimal("2.0"), "holding_bars": 2},
            ),
        )
        for trial in trials:
            self.ledger.append_trial(trial)
        trial_ids = tuple(trial.trial_id for trial in trials)
        evidence = ValidationEvidence(
            evidence_id="evidence-1",
            search_id=self.plan.search_id,
            strategy_id=self.strategy.strategy_id,
            strategy_version=self.strategy.version,
            split_plan_sha256="c" * 64,
            fold_ids=("fold-0001", "fold-0002"),
            purging_applied=True,
            embargo_ns=10,
            baseline_kinds=(BaselineKind.NO_TRADE, BaselineKind.BUY_AND_HOLD),
            multiple_testing=MultipleTestingEvidence(
                tried_trial_ids=trial_ids,
                pbo_trial_ids=trial_ids,
                deflated_sharpe_trial_ids=trial_ids,
                cscv_fold_count=4,
                pbo_probability=Decimal("0.25"),
                deflated_sharpe=Decimal("0.20"),
            ),
            cost_distribution=self.distribution("BPS"),
            capacity_distribution=self.distribution("USD_NOTIONAL"),
            fill_uncertainty_distribution=self.distribution("FILL_RATIO"),
            completed_fidelity_stages=(
                FidelityStage.SYNTHETIC,
                FidelityStage.BAR_REPLAY,
                FidelityStage.EVENT_REPLAY,
            ),
            claimed_fidelity_stage=FidelityStage.EVENT_REPLAY,
            synthetic_only=False,
            created_at_ns=1_000,
        )
        return trials, evidence

    def request(self, evidence: ValidationEvidence) -> PromotionRequest:
        review = IndependentReview(
            review_id="review-1",
            reviewer_id="independent-human",
            reviewer_role=DatasetRole.INDEPENDENT_EVALUATOR,
            evidence_sha256=evidence.sha256(),
            approved=True,
            human_approval_id="approval-1",
            minority_findings=("capacity sensitivity remains",),
            unresolved_findings=(),
            reviewed_at_ns=1_100,
        )
        return PromotionRequest(
            request_id="request-1",
            candidate_trial_id="trial-1",
            search_id=self.plan.search_id,
            strategy_id=self.strategy.strategy_id,
            strategy_version=self.strategy.version,
            requested_by_id="model-council",
            requested_by_role=DatasetRole.MODEL_COUNCIL,
            validation_evidence_sha256=evidence.sha256(),
            independent_review=review,
            rollback_plan="Return to NO_TRADE and preserve evidence",
            unresolved_assumption_breaks=(),
            requested_at_ns=1_200,
        )

    def test_trials_cannot_exceed_declared_search_budget(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "TRIAL_EXCEEDS_SEARCH_BUDGET"):
            self.ledger.append_trial(self.trial("trial-3", 3))

    def test_trials_must_use_declared_seed(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "TRIAL_SEED_OUTSIDE_SEARCH_PLAN"):
            self.ledger.append_trial(self.trial("wrong-seed", 1, seed=13))

    def test_trial_parameter_set_must_match_search_plan(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "TRIAL_PARAMETER_SET_MISMATCH"):
            self.ledger.append_trial(
                self.trial(
                    "missing-parameter",
                    1,
                    parameters={"threshold": Decimal("1.5")},
                )
            )
        with self.assertRaisesRegex(InvariantViolation, "TRIAL_PARAMETER_SET_MISMATCH"):
            self.ledger.append_trial(
                self.trial(
                    "extra-parameter",
                    1,
                    parameters={
                        "threshold": Decimal("1.5"),
                        "holding_bars": 1,
                        "invented": True,
                    },
                )
            )

    def test_trial_parameter_values_must_be_declared(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "TRIAL_PARAMETER_OUTSIDE_SEARCH_PLAN"):
            self.ledger.append_trial(
                self.trial(
                    "unknown-value",
                    1,
                    parameters={
                        "threshold": Decimal("9.9"),
                        "holding_bars": 1,
                    },
                )
            )

    def test_train_window_rolls_with_each_test_window(self) -> None:
        samples = (
            TemporalSample("old-10", 10, 10, 15, 10, 10, 10, 10, 10),
            TemporalSample("train-40", 40, 40, 45, 40, 40, 40, 40, 40),
            TemporalSample("train-95", 95, 95, 100, 95, 95, 95, 95, 95),
            TemporalSample("past-test-105", 105, 105, 110, 105, 105, 105, 105, 105),
            TemporalSample("embargo-125", 125, 125, 130, 125, 125, 125, 125, 125),
            TemporalSample("test-135", 135, 135, 140, 135, 135, 135, 135, 135),
        )
        plan = build_purged_walk_forward_plan(
            samples,
            WalkForwardConfig(
                first_test_start_ns=100,
                train_window_ns=100,
                test_window_ns=20,
                step_ns=30,
                embargo_ns=10,
                fold_count=2,
                min_train_samples=2,
                min_test_samples=1,
            ),
        )
        second = plan.folds[1]
        self.assertEqual(second.train_start_ns, 30)
        self.assertNotIn("old-10", second.train_sample_ids)
        self.assertIn("old-10", second.purged_sample_ids)

    def test_promotion_revalidates_mutated_fidelity_evidence(self) -> None:
        _, evidence = self.validation_fixture()
        request = self.request(evidence)
        object.__setattr__(
            evidence,
            "completed_fidelity_stages",
            (FidelityStage.SYNTHETIC, FidelityStage.EVENT_REPLAY),
        )
        decision = PromotionGate().evaluate(request, evidence, self.ledger)
        self.assertEqual(decision.state, PromotionState.BLOCKED)
        self.assertIn("FIDELITY_STAGE_GAP", decision.reasons)

    def test_promotion_revalidates_mutated_edge_claim(self) -> None:
        _, evidence = self.validation_fixture()
        request = self.request(evidence)
        object.__setattr__(evidence, "strategy_edge_proven", True)
        decision = PromotionGate().evaluate(request, evidence, self.ledger)
        self.assertEqual(decision.state, PromotionState.BLOCKED)
        self.assertIn(
            "VALIDATION_DIAGNOSTICS_CANNOT_PROVE_EDGE",
            decision.reasons,
        )

    def test_promotion_rejects_mutated_request_live_lock(self) -> None:
        _, evidence = self.validation_fixture()
        request = self.request(evidence)
        object.__setattr__(request, "live_trading_state", "UNLOCKED")
        decision = PromotionGate().evaluate(request, evidence, self.ledger)
        self.assertEqual(decision.state, PromotionState.BLOCKED)
        self.assertIn("PROMOTION_REQUEST_CANNOT_CHANGE_LIVE_LOCK", decision.reasons)
        self.assertEqual(decision.live_trading_state, "HARD_LOCKED")


if __name__ == "__main__":
    unittest.main()
