#!/usr/bin/env python3
"""Independent acceptance verifier for execution calibration and shadow evidence.

The verifier exercises the public contracts from execution evidence, contextual
calibration, shadow counterfactual evidence and conservative research capacity.
It deliberately cannot qualify a broker feed, calibrate a production simulator,
authorize capital, prove strategy edge or unlock live trading.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Callable
from uuid import UUID

from marketos.capacity import (
    CapacityDistribution,
    CapacityDistributionKind,
    CapacityInputs,
    compute_research_capacity_bound,
)
from marketos.datafabric import RawEvidenceStore
from marketos.errors import InvariantViolation
from marketos.execution_calibration import (
    CalibrationDecisionState,
    CalibrationGate,
    CalibrationRequest,
    CalibrationReview,
    CalibrationTolerance,
    DistributionKind,
    ExecutionAssumptions,
    ExecutionFidelityStage,
    ExecutionInputCapability,
    FillModelDefinition,
    GapStatus,
    PredictedExecutionDistribution,
    PredictionSurface,
    QuantileDistribution,
    RealityGapFamily,
    build_reality_gap_report,
)
from marketos.execution_evidence import (
    EvidenceOrigin,
    ExecutionContext,
    ExecutionEvidenceLedger,
    ExecutionOutcome,
    Marketability,
)
from marketos.experiments import DatasetRole
from marketos.money import Money, Price, Quantity
from marketos.orders import OrderSide, OrderType
from marketos.shadow_evidence import (
    ShadowComparison,
    ShadowDecision,
    ShadowEvidenceLedger,
)


VENUE_ID = UUID("00000000-0000-0000-0000-000000020010")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def _expect_invariant(operation: Callable[[], object], code: str) -> None:
    try:
        operation()
    except InvariantViolation:
        return
    raise AssertionError(code)


def _context(*, instrument_id: str = "AAPL") -> ExecutionContext:
    return ExecutionContext(
        instrument_id=instrument_id,
        venue_id=VENUE_ID,
        order_type=OrderType.MARKET,
        side=OrderSide.BUY,
        marketability=Marketability.MARKETABLE,
        size_bucket="SMALL",
        regime="NORMAL",
    )


def _raw_sha(raw: RawEvidenceStore, label: str, *, source_id: str) -> str:
    return raw.put(
        f"execution-calibration-acceptance:{label}".encode(),
        source_id=source_id,
        retrieved_at_ns=900,
        media_type="application/octet-stream",
        rights_policy_ids=("execution-acceptance-rights",),
    ).content_sha256


def _outcome(
    raw: RawEvidenceStore,
    outcome_id: str,
    origin: EvidenceOrigin,
    *,
    fill_ratio: str = "0.8",
    shortfall_bps: str = "4",
    latency_ns: int = 30,
    cancelled: bool = False,
) -> ExecutionOutcome:
    submitted = Decimal("10")
    filled = submitted * Decimal(fill_ratio)
    arrival = Decimal("100")
    fill_price = arrival * (
        Decimal("1") + Decimal(shortfall_bps) / Decimal("10000")
    )
    return ExecutionOutcome(
        outcome_id=outcome_id,
        version=1,
        order_id=f"order:{outcome_id}",
        context=_context(),
        origin=origin,
        source_id="broker-acceptance" if origin is EvidenceOrigin.BROKER_OBSERVED else "research-acceptance",
        external_execution_id=(
            f"broker-fill:{outcome_id}"
            if origin is EvidenceOrigin.BROKER_OBSERVED
            else None
        ),
        raw_content_sha256=_raw_sha(
            raw,
            outcome_id,
            source_id=(
                "broker-acceptance"
                if origin is EvidenceOrigin.BROKER_OBSERVED
                else "research-acceptance"
            ),
        ),
        submitted_quantity=Quantity.positive(submitted),
        filled_quantity=Quantity.parse(filled),
        arrival_price=Price.parse("USD", arrival, tick_size="0.01"),
        average_fill_price=Price.parse("USD", fill_price, tick_size="0.01"),
        fee=Money.zero("USD"),
        financing=Money.zero("USD"),
        opportunity_cost=Money.zero("USD"),
        submitted_at_ns=1_000,
        acknowledged_at_ns=1_005,
        completed_at_ns=1_000 + latency_ns,
        cancelled=cancelled,
        rejected=False,
    )


def _assumptions() -> ExecutionAssumptions:
    return ExecutionAssumptions(
        marketability_rule="Point-in-time best bid/ask classification",
        latency_model="Venue-conditioned latency distribution",
        spread_model="Quoted spread conditional on marketability",
        depth_model="Visible point-in-time depth only",
        participation_model="Contextual participation cap",
        queue_model="Explicit uncertain FIFO approximation",
        partial_fill_model="Partial fill from depth and queue",
        cancellation_model="Contextual cancellation hazard",
        reject_model="Venue and order-constraint reject model",
        fee_model="Venue, clearing and regulatory fees",
        financing_model="Financing and borrow by holding horizon",
        opportunity_cost_model="Unfilled quantity marked later",
        impact_model="Temporary and permanent contextual impact",
    )


def _model() -> FillModelDefinition:
    return FillModelDefinition(
        model_id="acceptance-fill-challenger",
        version=1,
        challenger_of_model_id="acceptance-fill-incumbent",
        completed_fidelity_stages=(
            ExecutionFidelityStage.S0_BAR,
            ExecutionFidelityStage.S1_TRADE_QUOTE,
            ExecutionFidelityStage.S2_L2_DEPTH,
        ),
        claimed_fidelity_stage=ExecutionFidelityStage.S2_L2_DEPTH,
        input_capabilities=(
            ExecutionInputCapability.BARS,
            ExecutionInputCapability.TRADES_QUOTES,
            ExecutionInputCapability.L2_DEPTH,
        ),
        assumptions=_assumptions(),
        trained_through_ns=1_000,
        code_sha256="a" * 64,
        config_sha256="b" * 64,
        dependency_lock_sha256="c" * 64,
    )


def _distribution(
    kind: DistributionKind,
    p05: str,
    p50: str,
    p95: str,
) -> QuantileDistribution:
    return QuantileDistribution(
        kind=kind,
        p05=Decimal(p05),
        p50=Decimal(p50),
        p95=Decimal(p95),
        sample_count=100,
    )


def _prediction(
    model: FillModelDefinition,
    *,
    prediction_id: str = "acceptance-prediction",
    shortfall_p50: str = "4",
    shortfall_p95: str = "8",
) -> PredictedExecutionDistribution:
    return PredictedExecutionDistribution(
        prediction_id=prediction_id,
        model_id=model.model_id,
        model_version=model.version,
        model_definition_sha256=model.sha256(),
        context=_context(),
        as_of_ns=1_900,
        fill_ratio=_distribution(DistributionKind.FILL_RATIO, "0.4", "0.8", "1.0"),
        shortfall_bps=_distribution(
            DistributionKind.SHORTFALL_BPS,
            "0",
            shortfall_p50,
            shortfall_p95,
        ),
        latency_ns=_distribution(DistributionKind.LATENCY_NS, "10", "30", "50"),
        cancellation_probability=_distribution(
            DistributionKind.CANCELLATION_PROBABILITY,
            "0",
            "0",
            "1",
        ),
        reject_probability=_distribution(
            DistributionKind.REJECT_PROBABILITY,
            "0",
            "0",
            "0",
        ),
    )


def _surface(
    model: FillModelDefinition,
    prediction: PredictedExecutionDistribution,
    *,
    surface_id: str = "acceptance-surface",
) -> PredictionSurface:
    return PredictionSurface(
        surface_id=surface_id,
        version=1,
        model_definition_sha256=model.sha256(),
        model_id=model.model_id,
        model_version=model.version,
        predictions=(prediction,),
        created_at_ns=2_000,
    )


def _tolerances() -> tuple[CalibrationTolerance, ...]:
    return (
        CalibrationTolerance(
            family=RealityGapFamily.FILL_RATIO,
            max_p50_absolute_gap=Decimal("0.05"),
            max_p95_absolute_gap=Decimal("0.05"),
            min_observations=5,
        ),
        CalibrationTolerance(
            family=RealityGapFamily.SHORTFALL_BPS,
            max_p50_absolute_gap=Decimal("1"),
            max_p95_absolute_gap=Decimal("1"),
            min_observations=5,
        ),
        CalibrationTolerance(
            family=RealityGapFamily.LATENCY_NS,
            max_p50_absolute_gap=Decimal("1"),
            max_p95_absolute_gap=Decimal("1"),
            min_observations=5,
        ),
        CalibrationTolerance(
            family=RealityGapFamily.CANCELLATION_RATE,
            max_p50_absolute_gap=Decimal("0.1"),
            max_p95_absolute_gap=Decimal("0.1"),
            min_observations=5,
        ),
        CalibrationTolerance(
            family=RealityGapFamily.REJECT_RATE,
            max_p50_absolute_gap=Decimal("0.1"),
            max_p95_absolute_gap=Decimal("0.1"),
            min_observations=5,
        ),
    )


def _observed_outcomes(raw: RawEvidenceStore) -> tuple[ExecutionOutcome, ...]:
    specifications = (
        ("0.4", "0", 10, False),
        ("0.6", "2", 20, False),
        ("0.8", "4", 30, False),
        ("0.9", "6", 40, False),
        ("1.0", "8", 50, True),
    )
    return tuple(
        _outcome(
            raw,
            f"acceptance-observed-{index}",
            EvidenceOrigin.BROKER_OBSERVED,
            fill_ratio=fill_ratio,
            shortfall_bps=shortfall,
            latency_ns=latency,
            cancelled=cancelled,
        )
        for index, (fill_ratio, shortfall, latency, cancelled) in enumerate(
            specifications,
            start=1,
        )
    )


def _build_report(root: Path, *, bad_shortfall: bool = False):
    raw = RawEvidenceStore(root / "raw")
    ledger = ExecutionEvidenceLedger(
        root / "execution.sqlite",
        raw_evidence_store=raw,
    )
    try:
        model = _model()
        prediction = _prediction(
            model,
            shortfall_p50="100" if bad_shortfall else "4",
            shortfall_p95="120" if bad_shortfall else "8",
        )
        surface = _surface(model, prediction)
        outcomes = _observed_outcomes(raw)
        for outcome in outcomes:
            ledger.append(outcome)
        report = build_reality_gap_report(
            report_id=(
                "acceptance-bad-gap" if bad_shortfall else "acceptance-gap"
            ),
            version=1,
            model_definition=model,
            prediction_surface=surface,
            evidence_ledger=ledger,
            observed_outcome_ids=tuple(outcome.outcome_id for outcome in outcomes),
            tolerances=_tolerances(),
            created_at_ns=2_500,
        )
        return model, report
    finally:
        ledger.close()
        raw.close()


def _capacity_distribution(
    kind: CapacityDistributionKind,
    p05: str,
    p50: str,
    p95: str,
) -> CapacityDistribution:
    return CapacityDistribution(
        kind=kind,
        p05=Decimal(p05),
        p50=Decimal(p50),
        p95=Decimal(p95),
        sample_count=100,
    )


def _capacity_inputs(**overrides) -> CapacityInputs:
    values = dict(
        capacity_id="acceptance-capacity",
        version=1,
        strategy_id="acceptance-strategy",
        strategy_version=1,
        currency="USD",
        gross_edge_bps=_capacity_distribution(
            CapacityDistributionKind.GROSS_EDGE_BPS,
            "20",
            "30",
            "45",
        ),
        impact_bps=_capacity_distribution(
            CapacityDistributionKind.IMPACT_BPS,
            "1",
            "3",
            "5",
        ),
        operating_cost_bps=_capacity_distribution(
            CapacityDistributionKind.OPERATING_COST_BPS,
            "1",
            "2",
            "3",
        ),
        uncertainty_bps=_capacity_distribution(
            CapacityDistributionKind.UNCERTAINTY_BPS,
            "0.5",
            "1",
            "2",
        ),
        liquidity_notional_limit=Money.from_decimal("USD", "1000000"),
        concentration_notional_limit=Money.from_decimal("USD", "600000"),
        turnover_notional_limit=Money.from_decimal("USD", "800000"),
        crowding_notional_limit=Money.from_decimal("USD", "700000"),
        portfolio_interaction_notional_limit=Money.from_decimal("USD", "500000"),
        borrow_required=False,
        borrow_available=False,
        borrow_notional_limit=None,
        calibration_report_sha256="d" * 64,
        validation_evidence_sha256="e" * 64,
        shadow_evidence_root_sha256="f" * 64,
        created_at_ns=5_000,
    )
    values.update(overrides)
    return CapacityInputs(**values)


def _trade_shadow(raw: RawEvidenceStore, comparison_id: str) -> ShadowComparison:
    return ShadowComparison(
        comparison_id=comparison_id,
        version=1,
        strategy_id="acceptance-strategy",
        strategy_version=1,
        decision=ShadowDecision.TRADE_INTENT,
        decision_reason="Point-in-time signal passed research controls",
        intent_id=f"intent:{comparison_id}",
        intent_sha256="a" * 64,
        context=_context(),
        prediction_sha256="b" * 64,
        model_definition_sha256="c" * 64,
        reference_market_sha256="d" * 64,
        source_dataset_sha256="e" * 64,
        raw_content_sha256=_raw_sha(
            raw,
            f"shadow:{comparison_id}",
            source_id="shadow-acceptance",
        ),
        decision_time_ns=1_000,
        prediction_available_at_ns=1_000,
        later_observation_available_at_ns=1_100,
        predicted_fill_ratio=Decimal("0.80"),
        predicted_shortfall_bps=Decimal("4"),
        opportunity_fill_ratio=Decimal("0.60"),
        opportunity_shortfall_bps=Decimal("6"),
        fill_ratio_gap=Decimal("-0.20"),
        shortfall_gap_bps=Decimal("2"),
        linked_broker_outcome_sha256=None,
        broker_fill_claimed=False,
    )


def verify_execution_calibration() -> dict[str, object]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def run(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
            checks[name] = True
        except Exception as exc:  # retain each diagnostic independently
            checks[name] = False
            errors.append(f"{name}:{type(exc).__name__}:{exc}")

    def broker_truth_firewall() -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-truth-") as temp:
            root = Path(temp)
            raw = RawEvidenceStore(root / "raw")
            ledger = ExecutionEvidenceLedger(root / "execution.sqlite", raw_evidence_store=raw)
            try:
                paper = _outcome(raw, "paper", EvidenceOrigin.PAPER)
                broker = _outcome(raw, "broker", EvidenceOrigin.BROKER_OBSERVED)
                ledger.append(paper)
                ledger.append(broker)
                _require(ledger.observed_outcomes() == (broker,), "NON_BROKER_ENTERED_OBSERVED_TRUTH")
                _require(not paper.is_observed_truth and broker.is_observed_truth, "OBSERVED_TRUTH_FLAG_MISMATCH")
                _expect_invariant(
                    lambda: replace(paper, external_execution_id="broker-fill:fake"),
                    "NON_BROKER_IMPERSONATION_ALLOWED",
                )
            finally:
                ledger.close()
                raw.close()

    run("broker_observed_truth_firewall", broker_truth_firewall)

    def immutable_execution_evidence() -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-ledger-") as temp:
            root = Path(temp)
            raw = RawEvidenceStore(root / "raw")
            path = root / "execution.sqlite"
            ledger = ExecutionEvidenceLedger(path, raw_evidence_store=raw)
            try:
                broker = _outcome(raw, "immutable", EvidenceOrigin.BROKER_OBSERVED)
                _require(ledger.append(broker), "EXECUTION_APPEND_FAILED")
                _require(not ledger.append(broker), "EXECUTION_IDEMPOTENCY_FAILED")
                connection = sqlite3.connect(path)
                try:
                    try:
                        connection.execute("DELETE FROM execution_outcomes WHERE outcome_id = ?", (broker.outcome_id,))
                    except sqlite3.DatabaseError:
                        pass
                    else:
                        raise AssertionError("EXECUTION_DELETE_TRIGGER_MISSING")
                finally:
                    connection.close()
            finally:
                ledger.close()
                raw.close()

    run("append_only_execution_evidence", immutable_execution_evidence)

    def explicit_model_contract() -> None:
        model = _model()
        _require(not model.production_calibrated, "MODEL_PRODUCTION_CALIBRATION_ESCALATED")
        _require(not model.execution_simulator_calibrated, "SIMULATOR_CALIBRATION_ESCALATED")
        _expect_invariant(
            lambda: replace(model.assumptions, impact_model=""),
            "MISSING_MODEL_ASSUMPTION_ACCEPTED",
        )
        _expect_invariant(
            lambda: replace(
                model,
                completed_fidelity_stages=(
                    ExecutionFidelityStage.S0_BAR,
                    ExecutionFidelityStage.S2_L2_DEPTH,
                ),
                claimed_fidelity_stage=ExecutionFidelityStage.S2_L2_DEPTH,
                input_capabilities=(
                    ExecutionInputCapability.BARS,
                    ExecutionInputCapability.L2_DEPTH,
                ),
            ),
            "FIDELITY_STAGE_GAP_ACCEPTED",
        )

    run("explicit_assumptions_and_contiguous_fidelity", explicit_model_contract)

    def contextual_prediction_contract() -> None:
        model = _model()
        prediction = _prediction(model)
        _require(prediction.context_key == _context().sha256(), "PREDICTION_CONTEXT_KEY_MISMATCH")
        _expect_invariant(
            lambda: _distribution(DistributionKind.FILL_RATIO, "0", "0.5", "1.1"),
            "OUT_OF_RANGE_PROBABILITY_ACCEPTED",
        )
        duplicate = replace(prediction, prediction_id="acceptance-prediction-duplicate")
        _expect_invariant(
            lambda: PredictionSurface(
                surface_id="duplicate-context-surface",
                version=1,
                model_definition_sha256=model.sha256(),
                model_id=model.model_id,
                model_version=model.version,
                predictions=(prediction, duplicate),
                created_at_ns=2_000,
            ),
            "DUPLICATE_CONTEXT_PREDICTION_ACCEPTED",
        )

    run("contextual_prediction_surface_is_strict", contextual_prediction_contract)

    def reality_gap_families_do_not_mask() -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-gap-good-") as temp:
            _model_good, good = _build_report(Path(temp))
        _require(good.all_required_gaps_passed, "MATCHED_REALITY_GAP_DID_NOT_PASS")
        _require(len(good.context_gaps) == 5, "REALITY_GAP_FAMILY_COUNT_MISMATCH")
        _require(all(gap.status is GapStatus.PASS for gap in good.context_gaps), "REALITY_GAP_FAMILY_NOT_INDEPENDENT")
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-gap-bad-") as temp:
            _model_bad, bad = _build_report(Path(temp), bad_shortfall=True)
        _require(not bad.all_required_gaps_passed, "FAILED_FAMILY_WAS_AGGREGATE_MASKED")
        _require(any(gap.status is not GapStatus.PASS for gap in bad.context_gaps), "FAILED_GAP_FAMILY_NOT_EXPOSED")
        _require(any(gap.status is GapStatus.PASS for gap in bad.context_gaps), "BAD_FIXTURE_DID_NOT_ISOLATE_FAMILY_FAILURE")

    run("reality_gap_families_cannot_be_masked", reality_gap_families_do_not_mask)

    def independent_challenger_gate() -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-gate-") as temp:
            model, report = _build_report(Path(temp))
        review = CalibrationReview(
            review_id="acceptance-review",
            reviewer_id="independent-human",
            reviewer_role=DatasetRole.INDEPENDENT_EVALUATOR,
            report_sha256=report.sha256(),
            approved=True,
            human_approval_id="acceptance-human-approval",
            minority_findings=("Sparse stress observations remain a concern",),
            unresolved_findings=(),
            reviewed_at_ns=2_600,
        )
        request = CalibrationRequest(
            request_id="acceptance-calibration-request",
            challenger_model_id=model.model_id,
            challenger_model_version=model.version,
            model_definition_sha256=model.sha256(),
            report_sha256=report.sha256(),
            requested_by_id="model-council",
            requested_by_role=DatasetRole.MODEL_COUNCIL,
            independent_review=review,
            rollback_plan="Retain incumbent and disable challenger predictions",
            requested_at_ns=2_700,
        )
        decision = CalibrationGate().evaluate(request, report, model)
        _require(decision.state is CalibrationDecisionState.ELIGIBLE_AS_CHALLENGER, "VALID_CHALLENGER_WAS_NOT_ELIGIBLE")
        _require(not decision.production_calibrated, "CHALLENGER_GATE_CALIBRATED_PRODUCTION")
        _require(not decision.execution_simulator_calibrated, "CHALLENGER_GATE_CALIBRATED_SIMULATOR")
        bad_request = replace(
            request,
            independent_review=replace(review, reviewer_role=DatasetRole.MODEL_COUNCIL),
        )
        blocked = CalibrationGate().evaluate(bad_request, report, model)
        _require(blocked.state is CalibrationDecisionState.BLOCKED, "NON_INDEPENDENT_REVIEW_WAS_ACCEPTED")
        _require("INDEPENDENT_CALIBRATION_REVIEW_REQUIRED" in blocked.reasons, "INDEPENDENCE_FAILURE_NOT_EXPLICIT")

    run("independent_review_only_challenger_gate", independent_challenger_gate)

    def shadow_is_never_observed_truth() -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-shadow-contract-") as temp:
            raw = RawEvidenceStore(Path(temp) / "raw")
            try:
                shadow = _trade_shadow(raw, "shadow-contract")
                _require(shadow.evidence_origin is EvidenceOrigin.SHADOW_COUNTERFACTUAL, "SHADOW_ORIGIN_ESCALATED")
                _require(not shadow.is_observed_truth, "SHADOW_BECAME_OBSERVED_TRUTH")
                _expect_invariant(
                    lambda: replace(shadow, broker_fill_claimed=True),
                    "SHADOW_BROKER_FILL_CLAIM_ACCEPTED",
                )
            finally:
                raw.close()

    run("shadow_counterfactual_truth_firewall", shadow_is_never_observed_truth)

    def immutable_shadow_evidence() -> None:
        with tempfile.TemporaryDirectory(prefix="marketos-acceptance-shadow-ledger-") as temp:
            root = Path(temp)
            raw = RawEvidenceStore(root / "raw")
            execution = ExecutionEvidenceLedger(root / "execution.sqlite", raw_evidence_store=raw)
            path = root / "shadow.sqlite"
            shadow_ledger = ShadowEvidenceLedger(
                path,
                raw_evidence_store=raw,
                execution_evidence_ledger=execution,
            )
            try:
                shadow = _trade_shadow(raw, "shadow-immutable")
                _require(shadow_ledger.append(shadow), "SHADOW_APPEND_FAILED")
                _require(not shadow_ledger.append(shadow), "SHADOW_IDEMPOTENCY_FAILED")
                connection = sqlite3.connect(path)
                try:
                    try:
                        connection.execute("DELETE FROM shadow_comparisons WHERE comparison_id = ?", (shadow.comparison_id,))
                    except sqlite3.DatabaseError:
                        pass
                    else:
                        raise AssertionError("SHADOW_DELETE_TRIGGER_MISSING")
                finally:
                    connection.close()
            finally:
                shadow_ledger.close()
                execution.close()
                raw.close()

    run("append_only_shadow_evidence", immutable_shadow_evidence)

    def conservative_capacity_bound() -> None:
        result = compute_research_capacity_bound(_capacity_inputs())
        _require(result.lower_confidence_net_edge_bps == Decimal("10"), "CAPACITY_EDGE_NOT_CONSERVATIVE")
        _require(result.research_notional_bound.to_decimal() == Decimal("500000.00"), "CAPACITY_DID_NOT_BIND_MINIMUM_CONSTRAINT")
        _require(result.binding_constraint == "PORTFOLIO_INTERACTION_NOTIONAL_LIMIT", "CAPACITY_BINDING_CONSTRAINT_WRONG")
        _require(not result.capital_authorized, "CAPACITY_AUTHORIZED_CAPITAL")
        _require(not result.capacity_qualified, "CAPACITY_SELF_QUALIFIED")
        _require(not result.strategy_edge_proven, "CAPACITY_PROVED_STRATEGY_EDGE")

    run("conservative_research_capacity_bound", conservative_capacity_bound)

    def fail_closed_capacity_and_authority() -> None:
        weak_edge = _capacity_distribution(
            CapacityDistributionKind.GROSS_EDGE_BPS,
            "8",
            "20",
            "30",
        )
        zero_edge = compute_research_capacity_bound(_capacity_inputs(gross_edge_bps=weak_edge))
        missing_constraint = compute_research_capacity_bound(_capacity_inputs(liquidity_notional_limit=None))
        borrow_unavailable = compute_research_capacity_bound(
            _capacity_inputs(
                borrow_required=True,
                borrow_available=False,
                borrow_notional_limit=Money.from_decimal("USD", "300000"),
            )
        )
        for result in (zero_edge, missing_constraint, borrow_unavailable):
            _require(result.research_notional_bound == Money.zero("USD"), "FAIL_CLOSED_CAPACITY_WAS_NONZERO")
            _require(bool(result.zero_reasons), "ZERO_CAPACITY_REASON_MISSING")
        _require(ExecutionEvidenceLedger.live_trading_state == "HARD_LOCKED", "LIVE_LOCK_WEAKENED")
        _require(ShadowEvidenceLedger.live_trading_state == "HARD_LOCKED", "SHADOW_LIVE_LOCK_WEAKENED")
        _require(CalibrationGate.live_trading_state == "HARD_LOCKED", "CALIBRATION_LIVE_LOCK_WEAKENED")
        _require(not ExecutionEvidenceLedger.observed_broker_feed_qualified, "BROKER_FEED_SELF_QUALIFIED")
        _require(not CalibrationGate.production_calibrated, "PRODUCTION_SIMULATOR_SELF_CALIBRATED")
        _require(not CalibrationGate.execution_simulator_calibrated, "EXECUTION_SIMULATOR_SELF_CALIBRATED")

    run("fail_closed_capacity_and_global_authority", fail_closed_capacity_and_authority)

    checks_passed = sum(1 for passed in checks.values() if passed)
    return {
        "ok": not errors and len(checks) == 10 and checks_passed == 10,
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": checks_passed,
        "errors": errors,
        "live_trading_state": "HARD_LOCKED",
        "profitability_state": "UNPROVEN",
        "execution_simulator_calibrated": False,
        "observed_broker_feed_qualified": False,
        "capacity_qualified": False,
        "capital_authorized": False,
        "strategy_edge_proven": False,
        "production_backend_selected": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_execution_calibration()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for name, passed in report["checks"].items():
            print(f"{'PASS' if passed else 'FAIL'} {name}")
        if report["errors"]:
            for error in report["errors"]:
                print(error)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
