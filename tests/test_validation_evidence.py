from __future__ import annotations

from decimal import Decimal
import unittest

from marketos.errors import InvariantViolation
from marketos.experiments import TrialRecord, TrialStatus
from marketos.validation import (
    BaselineKind,
    FidelityStage,
    MetricDistribution,
    MultipleTestingEvidence,
    ValidationEvidence,
)


class ValidationEvidenceTests(unittest.TestCase):
    @staticmethod
    def trial(
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
            parameters={"threshold": Decimal("2.0") + Decimal(ordinal) / 10},
            seed=ordinal,
            status=status,
            started_at_ns=1_000 + ordinal * 10,
            completed_at_ns=1_005 + ordinal * 10,
            data_cutoff_ns=900,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            metrics=(
                {}
                if metric is None
                else {"deflated_sharpe": Decimal(metric)}
            ),
            failure_reason=failure_reason,
        )

    def trials(self) -> tuple[TrialRecord, ...]:
        return (
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

    @staticmethod
    def distribution(
        unit: str,
        p05: str,
        p50: str,
        p95: str,
        *,
        sample_count: int = 100,
    ) -> MetricDistribution:
        return MetricDistribution(
            unit=unit,
            p05=Decimal(p05),
            p50=Decimal(p50),
            p95=Decimal(p95),
            sample_count=sample_count,
        )

    def multiple_testing(
        self,
        *,
        tried_trial_ids: tuple[str, ...] | None = None,
        pbo_trial_ids: tuple[str, ...] | None = None,
        deflated_sharpe_trial_ids: tuple[str, ...] | None = None,
    ) -> MultipleTestingEvidence:
        all_ids = tuple(trial.trial_id for trial in self.trials())
        return MultipleTestingEvidence(
            tried_trial_ids=(
                all_ids if tried_trial_ids is None else tried_trial_ids
            ),
            pbo_trial_ids=(all_ids if pbo_trial_ids is None else pbo_trial_ids),
            deflated_sharpe_trial_ids=(
                all_ids
                if deflated_sharpe_trial_ids is None
                else deflated_sharpe_trial_ids
            ),
            cscv_fold_count=8,
            pbo_probability=Decimal("0.25"),
            deflated_sharpe=Decimal("0.30"),
        )

    def evidence(self, **overrides) -> ValidationEvidence:
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
            multiple_testing=self.multiple_testing(),
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

    def test_valid_evidence_covers_every_trial_including_failures(self) -> None:
        evidence = self.evidence()
        evidence.validate_against_trials(self.trials())
        self.assertEqual(evidence.live_trading_state, "HARD_LOCKED")
        self.assertEqual(evidence.profitability_state, "UNPROVEN")
        self.assertFalse(evidence.strategy_edge_proven)
        self.assertEqual(evidence.sha256(), evidence.sha256())

    def test_no_trade_and_simple_baseline_are_both_mandatory(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "NO_TRADE_BASELINE_REQUIRED"):
            self.evidence(baseline_kinds=(BaselineKind.BUY_AND_HOLD,))
        with self.assertRaisesRegex(InvariantViolation, "SIMPLE_BASELINE_REQUIRED"):
            self.evidence(baseline_kinds=(BaselineKind.NO_TRADE,))

    def test_multiple_chronological_folds_purging_and_embargo_are_mandatory(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "MULTIPLE_FOLDS_REQUIRED"):
            self.evidence(fold_ids=("fold-0001",))
        with self.assertRaisesRegex(InvariantViolation, "PURGING_REQUIRED"):
            self.evidence(purging_applied=False)
        with self.assertRaisesRegex(InvariantViolation, "EMBARGO_REQUIRED"):
            self.evidence(embargo_ns=0)

    def test_pbo_population_must_match_all_trials(self) -> None:
        evidence = self.evidence(
            multiple_testing=self.multiple_testing(
                pbo_trial_ids=("trial-success", "trial-failed")
            )
        )
        with self.assertRaisesRegex(
            InvariantViolation,
            "PBO_TRIAL_POPULATION_MISMATCH",
        ):
            evidence.validate_against_trials(self.trials())

    def test_deflated_sharpe_population_must_match_all_trials(self) -> None:
        evidence = self.evidence(
            multiple_testing=self.multiple_testing(
                deflated_sharpe_trial_ids=("trial-success",)
            )
        )
        with self.assertRaisesRegex(
            InvariantViolation,
            "DEFLATED_SHARPE_POPULATION_MISMATCH",
        ):
            evidence.validate_against_trials(self.trials())

    def test_failed_and_abandoned_trials_cannot_be_omitted_from_tried_population(self) -> None:
        evidence = self.evidence(
            multiple_testing=self.multiple_testing(
                tried_trial_ids=("trial-success",)
            )
        )
        with self.assertRaisesRegex(
            InvariantViolation,
            "TRIED_TRIAL_POPULATION_MISMATCH",
        ):
            evidence.validate_against_trials(self.trials())

    def test_trial_search_or_strategy_mismatch_is_rejected(self) -> None:
        mismatched = TrialRecord(
            **{
                **self.trials()[0].as_kwargs(),
                "trial_id": "wrong-search",
                "search_id": "another-search",
                "ordinal": 4,
            }
        )
        with self.assertRaisesRegex(InvariantViolation, "VALIDATION_TRIAL_SCOPE_MISMATCH"):
            self.evidence().validate_against_trials((*self.trials(), mismatched))

    def test_metric_distributions_require_ordered_nonnegative_quantiles(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "INVALID_METRIC_QUANTILES"):
            self.distribution("BPS", "5", "3", "8")
        with self.assertRaisesRegex(InvariantViolation, "NEGATIVE_METRIC_DISTRIBUTION"):
            self.distribution("BPS", "-1", "3", "8")
        with self.assertRaisesRegex(InvariantViolation, "INSUFFICIENT_DISTRIBUTION_SAMPLES"):
            self.distribution("BPS", "1", "3", "8", sample_count=1)

    def test_all_cost_capacity_and_fill_distributions_are_required(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "COST_DISTRIBUTION_REQUIRED"):
            self.evidence(cost_distribution=None)
        with self.assertRaisesRegex(InvariantViolation, "CAPACITY_DISTRIBUTION_REQUIRED"):
            self.evidence(capacity_distribution=None)
        with self.assertRaisesRegex(InvariantViolation, "FILL_UNCERTAINTY_DISTRIBUTION_REQUIRED"):
            self.evidence(fill_uncertainty_distribution=None)

    def test_fidelity_stages_must_be_contiguous_and_claim_cannot_exceed_completion(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "FIDELITY_STAGE_GAP"):
            self.evidence(
                completed_fidelity_stages=(
                    FidelityStage.SYNTHETIC,
                    FidelityStage.EVENT_REPLAY,
                )
            )
        with self.assertRaisesRegex(InvariantViolation, "FIDELITY_CLAIM_EXCEEDS_COMPLETION"):
            self.evidence(
                completed_fidelity_stages=(FidelityStage.SYNTHETIC,),
                claimed_fidelity_stage=FidelityStage.EVENT_REPLAY,
            )

    def test_synthetic_only_evidence_cannot_claim_historical_or_shadow_fidelity(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "SYNTHETIC_ONLY_FIDELITY_CLAIM"):
            self.evidence(synthetic_only=True)
        synthetic = self.evidence(
            completed_fidelity_stages=(FidelityStage.SYNTHETIC,),
            claimed_fidelity_stage=FidelityStage.SYNTHETIC,
            synthetic_only=True,
        )
        synthetic.validate_against_trials(self.trials())
        self.assertEqual(synthetic.claimed_fidelity_stage, FidelityStage.SYNTHETIC)

    def test_shadow_cannot_be_marked_complete_without_prior_stages(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "FIDELITY_STAGE_GAP"):
            self.evidence(
                completed_fidelity_stages=(
                    FidelityStage.SYNTHETIC,
                    FidelityStage.SHADOW,
                ),
                claimed_fidelity_stage=FidelityStage.SHADOW,
            )

    def test_duplicate_trial_or_fold_identities_are_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "DUPLICATE_VALIDATION_FOLD"):
            self.evidence(fold_ids=("fold-0001", "fold-0001"))
        with self.assertRaisesRegex(InvariantViolation, "DUPLICATE_TRIED_TRIAL"):
            self.multiple_testing(
                tried_trial_ids=("trial-success", "trial-success")
            )


if __name__ == "__main__":
    unittest.main()
