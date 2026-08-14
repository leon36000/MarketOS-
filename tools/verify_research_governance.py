#!/usr/bin/env python3
"""Independent acceptance verifier for C10 research governance.

The verifier exercises immutable research evidence, hidden-holdout isolation,
temporal leakage controls, complete-population diagnostics and the shadow-only
promotion ceiling.  It deliberately does not select a strategy or claim edge.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Callable

from marketos.errors import InvariantViolation
from marketos.experiments import (
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
    TemporalSample,
    ValidationEvidence,
    WalkForwardConfig,
    build_purged_walk_forward_plan,
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def _strategy() -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="acceptance-reversal",
        version=1,
        hypothesis="Falsifiable liquidity-shock reversal",
        mechanism="Temporary order-flow imbalance mean-reverts",
        universe=("AAPL@XNAS", "MSFT@XNAS"),
        features=("spread-z@1", "signed-volume@1"),
        decision_rule="Enter only after threshold and abstention checks",
        position_rule="Risk-scaled capped long-only position",
        risk_budget={"gross_fraction": Decimal("0.10")},
        execution_policy="Passive-first and cancel on stale quote",
        abstention="Stale data, halt, crossed market, missing state",
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


def _search_plan() -> SearchPlan:
    return SearchPlan(
        search_id="acceptance-search",
        version=1,
        strategy_id="acceptance-reversal",
        strategy_version=1,
        objective_metric="DEFLATED_SHARPE",
        parameter_space={"threshold": (Decimal("1.5"), Decimal("2.0"))},
        seeds=(7, 11, 19),
        max_trials=3,
        created_at_ns=1_100,
        hidden_holdout_id="acceptance-holdout",
    )


def _trial(
    trial_id: str,
    ordinal: int,
    status: TrialStatus,
    *,
    metric: str | None = None,
    reason: str | None = None,
) -> TrialRecord:
    return TrialRecord(
        trial_id=trial_id,
        search_id="acceptance-search",
        strategy_id="acceptance-reversal",
        strategy_version=1,
        ordinal=ordinal,
        parameters={"threshold": Decimal("1.5") + Decimal(ordinal) / 10},
        seed=ordinal,
        status=status,
        started_at_ns=2_000 + ordinal * 10,
        completed_at_ns=2_005 + ordinal * 10,
        data_cutoff_ns=1_900,
        code_sha256="a" * 64,
        config_sha256="b" * 64,
        metrics=(
            {} if metric is None else {"deflated_sharpe": Decimal(metric)}
        ),
        failure_reason=reason,
    )


def _trials() -> tuple[TrialRecord, ...]:
    return (
        _trial("acceptance-success", 1, TrialStatus.SUCCEEDED, metric="0.30"),
        _trial(
            "acceptance-failed",
            2,
            TrialStatus.FAILED,
            reason="numerical instability",
        ),
        _trial(
            "acceptance-abandoned",
            3,
            TrialStatus.ABANDONED,
            reason="search budget exhausted",
        ),
    )


def _populate(ledger: ExperimentLedger) -> tuple[TrialRecord, ...]:
    ledger.append_strategy(_strategy())
    ledger.append_search_plan(_search_plan())
    trials = _trials()
    for trial in trials:
        ledger.append_trial(trial)
    return trials


def _distribution(unit: str, p05: str, p50: str, p95: str) -> MetricDistribution:
    return MetricDistribution(
        unit=unit,
        p05=Decimal(p05),
        p50=Decimal(p50),
        p95=Decimal(p95),
        sample_count=100,
    )


def _evidence(trials: tuple[TrialRecord, ...]) -> ValidationEvidence:
    trial_ids = tuple(trial.trial_id for trial in trials)
    return ValidationEvidence(
        evidence_id="acceptance-validation",
        search_id="acceptance-search",
        strategy_id="acceptance-reversal",
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
        cost_distribution=_distribution("BPS", "1", "3", "8"),
        capacity_distribution=_distribution(
            "USD_NOTIONAL", "100000", "500000", "1000000"
        ),
        fill_uncertainty_distribution=_distribution(
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


def _promotion_request(evidence: ValidationEvidence) -> PromotionRequest:
    review = IndependentReview(
        review_id="acceptance-review",
        reviewer_id="independent-human-reviewer",
        reviewer_role=DatasetRole.INDEPENDENT_EVALUATOR,
        evidence_sha256=evidence.sha256(),
        approved=True,
        human_approval_id="acceptance-human-approval",
        minority_findings=(
            "Capacity remains sensitive to stressed participation limits",
        ),
        unresolved_findings=(),
        reviewed_at_ns=6_000,
    )
    return PromotionRequest(
        request_id="acceptance-promotion",
        candidate_trial_id="acceptance-success",
        search_id="acceptance-search",
        strategy_id="acceptance-reversal",
        strategy_version=1,
        requested_by_id="research-orchestrator",
        requested_by_role=DatasetRole.MODEL_COUNCIL,
        validation_evidence_sha256=evidence.sha256(),
        independent_review=review,
        rollback_plan="Disable candidate, preserve evidence and revert to NO_TRADE",
        unresolved_assumption_breaks=(),
        requested_at_ns=6_100,
    )


def verify_research_governance() -> dict[str, object]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def run(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
            checks[name] = True
        except Exception as exc:  # retain each independent diagnostic
            checks[name] = False
            errors.append(f"{name}:{type(exc).__name__}:{exc}")

    with tempfile.TemporaryDirectory(prefix="marketos-research-governance-") as temp_dir:
        root = Path(temp_dir)

        def immutable_trial_evidence() -> None:
            path = root / "immutable.sqlite"
            with ExperimentLedger(path) as ledger:
                trials = _populate(ledger)
                _require(ledger.trials() == trials, "TRIAL_HISTORY_INCOMPLETE")
                _require(not ledger.append_trial(trials[0]), "TRIAL_IDEMPOTENCY_FAILED")
                _require(not hasattr(ledger, "delete_trial"), "TRIAL_DELETE_API_EXISTS")
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "DELETE FROM experiment_trials WHERE trial_id = ?",
                    (trials[0].trial_id,),
                )
            except sqlite3.DatabaseError:
                pass
            else:
                raise AssertionError("TRIAL_DELETE_TRIGGER_MISSING")
            finally:
                connection.close()

        run("immutable_complete_trial_evidence", immutable_trial_evidence)

        def hidden_holdout_isolation() -> None:
            policy = DatasetAccessPolicy(
                policy_id="acceptance-access",
                version=1,
                hidden_holdout_id="acceptance-holdout",
            )
            denied = policy.authorize(
                role=DatasetRole.OPTIMIZER,
                partition=DatasetPartition.HIDDEN_HOLDOUT,
                purpose="OPTIMIZATION",
                requested_at_ns=3_000,
            )
            allowed = policy.authorize(
                role=DatasetRole.INDEPENDENT_EVALUATOR,
                partition=DatasetPartition.HIDDEN_HOLDOUT,
                purpose="FINAL_EVALUATION",
                requested_at_ns=4_000,
            )
            _require(not denied.allowed, "OPTIMIZER_HOLDOUT_ACCESS_ALLOWED")
            _require(allowed.allowed, "INDEPENDENT_FINAL_EVALUATION_DENIED")
            with ExperimentLedger(root / "access.sqlite") as ledger:
                ledger.append_access_receipt(
                    AccessReceipt.from_decision(
                        receipt_id="denied-access",
                        decision=denied,
                    )
                )
                ledger.append_access_receipt(
                    AccessReceipt.from_decision(
                        receipt_id="allowed-access",
                        decision=allowed,
                    )
                )
                _require(
                    len(ledger.access_receipts()) == 2,
                    "ACCESS_AUDIT_INCOMPLETE",
                )

        run("hidden_holdout_isolation", hidden_holdout_isolation)

        def purge_and_embargo() -> None:
            samples = (
                TemporalSample("train-10", 10, 10, 15, 10, 10, 10, 10, 10),
                TemporalSample("train-40", 40, 40, 45, 40, 40, 40, 40, 40),
                TemporalSample("purged-95", 95, 95, 105, 95, 95, 95, 95, 95),
                TemporalSample("test-105", 105, 105, 110, 105, 105, 105, 105, 105),
                TemporalSample("embargo-125", 125, 125, 130, 125, 125, 125, 125, 125),
                TemporalSample("test-135", 135, 135, 140, 135, 135, 135, 135, 135),
                TemporalSample("future-160", 160, 160, 165, 160, 160, 160, 160, 160),
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
            _require(
                "purged-95" in plan.folds[0].purged_sample_ids,
                "LABEL_OVERLAP_NOT_PURGED",
            )
            _require(
                "embargo-125" in plan.folds[1].embargoed_sample_ids,
                "POST_TEST_EMBARGO_NOT_APPLIED",
            )
            for fold in plan.folds:
                accounted = (
                    len(fold.train_sample_ids)
                    + len(fold.test_sample_ids)
                    + len(fold.purged_sample_ids)
                    + len(fold.embargoed_sample_ids)
                    + len(fold.future_sample_ids)
                )
                _require(accounted == len(samples), "FOLD_ACCOUNTING_INCOMPLETE")

        run("purged_embargoed_walk_forward", purge_and_embargo)

        def lookahead_barriers() -> None:
            fields = (
                "feature_available_at_ns",
                "model_available_at_ns",
                "memory_available_at_ns",
                "embedding_available_at_ns",
                "prompt_available_at_ns",
            )
            for field in fields:
                values = dict(
                    sample_id=f"lookahead-{field}",
                    decision_time_ns=100,
                    label_start_ns=100,
                    label_end_ns=105,
                    feature_available_at_ns=100,
                    model_available_at_ns=100,
                    memory_available_at_ns=100,
                    embedding_available_at_ns=100,
                    prompt_available_at_ns=100,
                )
                values[field] = 101
                try:
                    TemporalSample(**values)
                except InvariantViolation:
                    continue
                raise AssertionError(f"LOOKAHEAD_NOT_BLOCKED:{field}")

        run("feature_model_memory_prompt_lookahead", lookahead_barriers)

        def required_baselines() -> None:
            trials = _trials()
            evidence = _evidence(trials)
            _require(
                BaselineKind.NO_TRADE in evidence.baseline_kinds,
                "NO_TRADE_BASELINE_MISSING",
            )
            _require(
                any(
                    baseline is not BaselineKind.NO_TRADE
                    for baseline in evidence.baseline_kinds
                ),
                "SIMPLE_BASELINE_MISSING",
            )
            try:
                ValidationEvidence(
                    **{
                        **evidence.canonical_dict(),
                        "baseline_kinds": (BaselineKind.BUY_AND_HOLD,),
                    }
                )
            except InvariantViolation:
                return
            raise AssertionError("NO_TRADE_BASELINE_NOT_ENFORCED")

        run("mandatory_no_trade_and_simple_baselines", required_baselines)

        def complete_multiple_testing_population() -> None:
            trials = _trials()
            evidence = _evidence(trials)
            evidence.validate_against_trials(trials)
            object.__setattr__(
                evidence.multiple_testing,
                "tried_trial_ids",
                ("acceptance-success",),
            )
            try:
                evidence.validate_against_trials(trials)
            except InvariantViolation as exc:
                _require(
                    "TRIED_TRIAL_POPULATION_MISMATCH" in str(exc),
                    "WRONG_POPULATION_DIAGNOSTIC",
                )
                return
            raise AssertionError("FAILED_TRIALS_OMITTED_WITHOUT_ERROR")

        run("complete_multiple_testing_population", complete_multiple_testing_population)

        def distributions_and_fidelity() -> None:
            evidence = _evidence(_trials())
            _require(evidence.cost_distribution is not None, "COST_DISTRIBUTION_MISSING")
            _require(
                evidence.capacity_distribution is not None,
                "CAPACITY_DISTRIBUTION_MISSING",
            )
            _require(
                evidence.fill_uncertainty_distribution is not None,
                "FILL_DISTRIBUTION_MISSING",
            )
            try:
                ValidationEvidence(
                    **{
                        **evidence.canonical_dict(),
                        "completed_fidelity_stages": (
                            FidelityStage.SYNTHETIC,
                        ),
                        "claimed_fidelity_stage": FidelityStage.EVENT_REPLAY,
                        "synthetic_only": True,
                    }
                )
            except InvariantViolation:
                return
            raise AssertionError("SYNTHETIC_FIDELITY_ESCALATION_ALLOWED")

        run("distributional_cost_capacity_and_fidelity", distributions_and_fidelity)

        def independent_shadow_ceiling() -> None:
            with ExperimentLedger(root / "promotion.sqlite") as ledger:
                trials = _populate(ledger)
                evidence = _evidence(trials)
                decision = PromotionGate().evaluate(
                    _promotion_request(evidence),
                    evidence,
                    ledger,
                )
                _require(
                    decision.state is PromotionState.ELIGIBLE_FOR_SHADOW,
                    "SHADOW_ELIGIBILITY_NOT_REACHED",
                )
                _require(not decision.champion_promoted, "CHAMPION_AUTO_PROMOTED")
                _require(not decision.strategy_edge_proven, "EDGE_FALSELY_PROVEN")
                try:
                    PromotionState("LIVE")
                except ValueError:
                    return
                raise AssertionError("LIVE_PROMOTION_STATE_EXISTS")

        run("independent_shadow_only_promotion", independent_shadow_ceiling)

        def stored_corruption_detection() -> None:
            path = root / "corruption.sqlite"
            with ExperimentLedger(path) as ledger:
                trials = _populate(ledger)
            connection = sqlite3.connect(path)
            connection.execute("DROP TRIGGER experiment_trials_no_update")
            connection.execute(
                "UPDATE experiment_trials SET record_json = ? WHERE trial_id = ?",
                ('{"trial_id":"tampered"}', trials[0].trial_id),
            )
            connection.commit()
            connection.close()
            with ExperimentLedger(path) as ledger:
                try:
                    ledger.trials()
                except InvariantViolation as exc:
                    _require(
                        "TRIAL_RECORD_HASH_MISMATCH" in str(exc),
                        "WRONG_CORRUPTION_DIAGNOSTIC",
                    )
                    return
            raise AssertionError("CORRUPTED_TRIAL_READ_SUCCEEDED")

        run("stored_research_evidence_integrity", stored_corruption_detection)

        def authority_boundaries() -> None:
            _require(
                ExperimentLedger.live_trading_state == "HARD_LOCKED",
                "EXPERIMENT_LIVE_LOCK_WEAKENED",
            )
            _require(
                ExperimentLedger.profitability_state == "UNPROVEN",
                "EXPERIMENT_PROFITABILITY_FALSELY_PROVEN",
            )
            _require(
                not ExperimentLedger.strategy_family_selected,
                "STRATEGY_FAMILY_FALSELY_SELECTED",
            )
            _require(
                not ExperimentLedger.strategy_edge_proven,
                "STRATEGY_EDGE_FALSELY_PROVEN",
            )
            _require(
                not ExperimentLedger.champion_promoted,
                "CHAMPION_FALSELY_PROMOTED",
            )
            _require(
                PromotionGate.live_trading_state == "HARD_LOCKED",
                "PROMOTION_LIVE_LOCK_WEAKENED",
            )

        run("authority_boundaries", authority_boundaries)

    passed = sum(checks.values())
    return {
        "ok": not errors and passed == 10,
        "checks": checks,
        "checks_total": 10,
        "checks_passed": passed,
        "errors": errors,
        "live_trading_state": "HARD_LOCKED",
        "profitability_state": "UNPROVEN",
        "strategy_family_selected": False,
        "strategy_edge_proven": False,
        "champion_promoted": False,
        "execution_simulator_calibrated": False,
        "production_backend_selected": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_research_governance()
    print(
        json.dumps(report, indent=2, sort_keys=True)
        if args.json
        else ("PASS" if report["ok"] else "FAIL")
    )
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
