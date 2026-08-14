#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one patch site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Trial execution must remain inside the immutable search budget and domain.
replace_once(
    "src/marketos/experiments.py",
    '''            if (
                trial.strategy_id,
                trial.strategy_version,
            ) != (
                plan.strategy_id,
                plan.strategy_version,
            ):
                raise InvariantViolation("TRIAL_STRATEGY_MISMATCH")
            ordinal_row = self._connection.execute(
''',
    '''            if (
                trial.strategy_id,
                trial.strategy_version,
            ) != (
                plan.strategy_id,
                plan.strategy_version,
            ):
                raise InvariantViolation("TRIAL_STRATEGY_MISMATCH")
            if trial.ordinal > plan.max_trials:
                raise InvariantViolation(
                    f"TRIAL_EXCEEDS_SEARCH_BUDGET:{trial.search_id}:"
                    f"ordinal={trial.ordinal}:max_trials={plan.max_trials}"
                )
            if trial.seed not in plan.seeds:
                raise InvariantViolation(
                    f"TRIAL_SEED_OUTSIDE_SEARCH_PLAN:{trial.search_id}:{trial.seed}"
                )
            if set(trial.parameters) != set(plan.parameter_space):
                raise InvariantViolation(
                    f"TRIAL_PARAMETER_SET_MISMATCH:{trial.search_id}:{trial.trial_id}"
                )
            for parameter_name, parameter_value in trial.parameters.items():
                allowed_values = plan.parameter_space[parameter_name]
                if not isinstance(allowed_values, tuple) or not allowed_values:
                    raise InvariantViolation(
                        f"INVALID_SEARCH_PARAMETER_DOMAIN:{plan.search_id}:"
                        f"{parameter_name}"
                    )
                allowed_json = {
                    canonical_json(allowed_value)
                    for allowed_value in allowed_values
                }
                if canonical_json(parameter_value) not in allowed_json:
                    raise InvariantViolation(
                        f"TRIAL_PARAMETER_OUTSIDE_SEARCH_PLAN:{trial.search_id}:"
                        f"{parameter_name}"
                    )
            ordinal_row = self._connection.execute(
''',
)

# The train window is rolling, not anchored forever to the first fold.
replace_once(
    "src/marketos/validation.py",
    '''    anchored_train_start = config.first_test_start_ns - config.train_window_ns
    previous_embargoes: list[tuple[int, int]] = []
''',
    '''    previous_embargoes: list[tuple[int, int]] = []
''',
)
replace_once(
    "src/marketos/validation.py",
    '''        test_start = config.first_test_start_ns + index * config.step_ns
        test_end = test_start + config.test_window_ns
''',
    '''        test_start = config.first_test_start_ns + index * config.step_ns
        train_start = test_start - config.train_window_ns
        test_end = test_start + config.test_window_ns
''',
)
replace_once(
    "src/marketos/validation.py",
    '''            elif decision < anchored_train_start:
''',
    '''            elif decision < train_start:
''',
)
replace_once(
    "src/marketos/validation.py",
    '''            train_start_ns=anchored_train_start,
''',
    '''            train_start_ns=train_start,
''',
)

# Promotion re-runs constructor-level integrity checks on the complete evidence
# graph so frozen-object bypasses cannot weaken the gate.
replace_once(
    "src/marketos/validation.py",
    '''    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def validate_against_trials(
''',
    '''    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def assert_integrity(self) -> None:
        multiple_testing = MultipleTestingEvidence(
            tried_trial_ids=self.multiple_testing.tried_trial_ids,
            pbo_trial_ids=self.multiple_testing.pbo_trial_ids,
            deflated_sharpe_trial_ids=(
                self.multiple_testing.deflated_sharpe_trial_ids
            ),
            cscv_fold_count=self.multiple_testing.cscv_fold_count,
            pbo_probability=self.multiple_testing.pbo_probability,
            deflated_sharpe=self.multiple_testing.deflated_sharpe,
        )

        def rebuild_distribution(
            value: MetricDistribution | None,
        ) -> MetricDistribution | None:
            if value is None:
                return None
            return MetricDistribution(
                unit=value.unit,
                p05=value.p05,
                p50=value.p50,
                p95=value.p95,
                sample_count=value.sample_count,
            )

        ValidationEvidence(
            evidence_id=self.evidence_id,
            search_id=self.search_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            split_plan_sha256=self.split_plan_sha256,
            fold_ids=self.fold_ids,
            purging_applied=self.purging_applied,
            embargo_ns=self.embargo_ns,
            baseline_kinds=self.baseline_kinds,
            multiple_testing=multiple_testing,
            cost_distribution=rebuild_distribution(self.cost_distribution),
            capacity_distribution=rebuild_distribution(
                self.capacity_distribution
            ),
            fill_uncertainty_distribution=rebuild_distribution(
                self.fill_uncertainty_distribution
            ),
            completed_fidelity_stages=self.completed_fidelity_stages,
            claimed_fidelity_stage=self.claimed_fidelity_stage,
            synthetic_only=self.synthetic_only,
            created_at_ns=self.created_at_ns,
            live_trading_state=self.live_trading_state,
            profitability_state=self.profitability_state,
            strategy_edge_proven=self.strategy_edge_proven,
        )

    def validate_against_trials(
''',
)

# Review and request integrity are independently reconstructable at the gate.
replace_once(
    "src/marketos/promotion.py",
    '''    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class PromotionRequest:
''',
    '''    def sha256(self) -> str:
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
''',
)
replace_once(
    "src/marketos/promotion.py",
    '''    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class PromotionDecision:
''',
    '''    def sha256(self) -> str:
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
''',
)
replace_once(
    "src/marketos/promotion.py",
    '''        reasons: list[str] = []
        evidence_sha256 = evidence.sha256()
        review = request.independent_review
''',
    '''        reasons: list[str] = []
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
''',
)
