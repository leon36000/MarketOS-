from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import UUID

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


VENUE_ID = UUID("00000000-0000-0000-0000-000000013010")


class ExecutionRealityGapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-reality-gap-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.raw = RawEvidenceStore(self.temp / "raw")
        self.addCleanup(self.raw.close)
        self.ledger = ExecutionEvidenceLedger(
            self.temp / "execution.sqlite",
            raw_evidence_store=self.raw,
        )
        self.addCleanup(self.ledger.close)
        self.definition = self.model_definition()
        self.context = self.execution_context()
        self.prediction = self.prediction_for(self.context)
        self.surface = PredictionSurface(
            surface_id="surface-1",
            version=1,
            model_definition_sha256=self.definition.sha256(),
            model_id=self.definition.model_id,
            model_version=self.definition.version,
            predictions=(self.prediction,),
            created_at_ns=2_000,
        )
        self.outcomes = self.append_observed_context(
            prefix="aapl",
            context=self.context,
        )
        self.tolerances = self.default_tolerances()

    @staticmethod
    def assumptions() -> ExecutionAssumptions:
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

    @classmethod
    def model_definition(
        cls,
        *,
        model_id: str = "fill-challenger",
        challenger_of_model_id: str | None = "fill-incumbent",
    ) -> FillModelDefinition:
        return FillModelDefinition(
            model_id=model_id,
            version=1,
            challenger_of_model_id=challenger_of_model_id,
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
            assumptions=cls.assumptions(),
            trained_through_ns=1_000,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            dependency_lock_sha256="c" * 64,
        )

    @staticmethod
    def execution_context(
        *,
        instrument_id: str = "AAPL",
        size_bucket: str = "SMALL",
        regime: str = "NORMAL",
    ) -> ExecutionContext:
        return ExecutionContext(
            instrument_id=instrument_id,
            venue_id=VENUE_ID,
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            marketability=Marketability.MARKETABLE,
            size_bucket=size_bucket,
            regime=regime,
        )

    @staticmethod
    def distribution(
        kind: DistributionKind,
        p05: str,
        p50: str,
        p95: str,
        *,
        sample_count: int = 100,
    ) -> QuantileDistribution:
        return QuantileDistribution(
            kind=kind,
            p05=Decimal(p05),
            p50=Decimal(p50),
            p95=Decimal(p95),
            sample_count=sample_count,
        )

    def prediction_for(
        self,
        context: ExecutionContext,
        *,
        prediction_id: str | None = None,
        shortfall_p50: str = "4",
        shortfall_p95: str = "8",
    ) -> PredictedExecutionDistribution:
        return PredictedExecutionDistribution(
            prediction_id=(
                f"prediction-{context.instrument_id.lower()}"
                if prediction_id is None
                else prediction_id
            ),
            model_id=self.definition.model_id,
            model_version=self.definition.version,
            model_definition_sha256=self.definition.sha256(),
            context=context,
            as_of_ns=1_900,
            fill_ratio=self.distribution(
                DistributionKind.FILL_RATIO,
                "0.4",
                "0.8",
                "1.0",
            ),
            shortfall_bps=self.distribution(
                DistributionKind.SHORTFALL_BPS,
                "0",
                shortfall_p50,
                shortfall_p95,
            ),
            latency_ns=self.distribution(
                DistributionKind.LATENCY_NS,
                "10",
                "30",
                "50",
            ),
            cancellation_probability=self.distribution(
                DistributionKind.CANCELLATION_PROBABILITY,
                "0",
                "0",
                "1",
            ),
            reject_probability=self.distribution(
                DistributionKind.REJECT_PROBABILITY,
                "0",
                "0",
                "0",
            ),
        )

    def raw_sha(self, suffix: str) -> str:
        return self.raw.put(
            f"broker-observed:{suffix}".encode(),
            source_id="broker-observed-fixture",
            retrieved_at_ns=900,
            media_type="application/octet-stream",
            rights_policy_ids=("execution-rights",),
        ).content_sha256

    def observed_outcome(
        self,
        outcome_id: str,
        context: ExecutionContext,
        *,
        version: int = 1,
        fill_ratio: str,
        shortfall_bps: str,
        latency_ns: int,
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
            version=version,
            order_id=f"order:{outcome_id}",
            context=context,
            origin=EvidenceOrigin.BROKER_OBSERVED,
            source_id="broker-observed-fixture",
            external_execution_id=f"broker-fill:{outcome_id}",
            raw_content_sha256=self.raw_sha(f"{outcome_id}:{version}"),
            submitted_quantity=Quantity.positive(submitted),
            filled_quantity=Quantity.parse(filled),
            arrival_price=Price.parse("USD", arrival, tick_size="0.01"),
            average_fill_price=Price.parse(
                "USD",
                fill_price,
                tick_size="0.01",
            ),
            fee=Money.zero("USD"),
            financing=Money.zero("USD"),
            opportunity_cost=Money.zero("USD"),
            submitted_at_ns=1_000,
            acknowledged_at_ns=1_005,
            completed_at_ns=1_000 + latency_ns,
            cancelled=cancelled,
            rejected=False,
        )

    def append_observed_context(
        self,
        *,
        prefix: str,
        context: ExecutionContext,
    ) -> tuple[ExecutionOutcome, ...]:
        specifications = (
            ("0.4", "0", 10, False),
            ("0.6", "2", 20, False),
            ("0.8", "4", 30, False),
            ("0.9", "6", 40, False),
            ("1.0", "8", 50, True),
        )
        outcomes = tuple(
            self.observed_outcome(
                f"{prefix}-{index}",
                context,
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
        for outcome in outcomes:
            self.ledger.append(outcome)
        return outcomes

    @staticmethod
    def default_tolerances(
        *,
        shortfall_p50: str = "1",
        shortfall_p95: str = "1",
        min_observations: int = 5,
    ) -> tuple[CalibrationTolerance, ...]:
        return (
            CalibrationTolerance(
                family=RealityGapFamily.FILL_RATIO,
                max_p50_absolute_gap=Decimal("0.05"),
                max_p95_absolute_gap=Decimal("0.05"),
                min_observations=min_observations,
            ),
            CalibrationTolerance(
                family=RealityGapFamily.SHORTFALL_BPS,
                max_p50_absolute_gap=Decimal(shortfall_p50),
                max_p95_absolute_gap=Decimal(shortfall_p95),
                min_observations=min_observations,
            ),
            CalibrationTolerance(
                family=RealityGapFamily.LATENCY_NS,
                max_p50_absolute_gap=Decimal("1"),
                max_p95_absolute_gap=Decimal("1"),
                min_observations=min_observations,
            ),
            CalibrationTolerance(
                family=RealityGapFamily.CANCELLATION_RATE,
                max_p50_absolute_gap=Decimal("0.1"),
                max_p95_absolute_gap=Decimal("0.1"),
                min_observations=min_observations,
            ),
            CalibrationTolerance(
                family=RealityGapFamily.REJECT_RATE,
                max_p50_absolute_gap=Decimal("0.1"),
                max_p95_absolute_gap=Decimal("0.1"),
                min_observations=min_observations,
            ),
        )

    def build_report(
        self,
        *,
        surface: PredictionSurface | None = None,
        outcome_ids: tuple[str, ...] | None = None,
        tolerances: tuple[CalibrationTolerance, ...] | None = None,
    ):
        return build_reality_gap_report(
            report_id="report-1",
            version=1,
            model_definition=self.definition,
            prediction_surface=self.surface if surface is None else surface,
            evidence_ledger=self.ledger,
            observed_outcome_ids=(
                tuple(outcome.outcome_id for outcome in self.outcomes)
                if outcome_ids is None
                else outcome_ids
            ),
            tolerances=(
                self.tolerances if tolerances is None else tolerances
            ),
            created_at_ns=2_500,
        )

    def test_report_is_deterministic_and_all_families_pass_independently(self) -> None:
        first = self.build_report()
        second = self.build_report(
            outcome_ids=tuple(
                reversed(tuple(outcome.outcome_id for outcome in self.outcomes))
            ),
            tolerances=tuple(reversed(self.tolerances)),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.sha256(), second.sha256())
        self.assertTrue(first.all_required_gaps_passed)
        self.assertEqual(len(first.context_gaps), 5)
        self.assertTrue(
            all(gap.status is GapStatus.PASS for gap in first.context_gaps)
        )
        self.assertEqual(first.missing_prediction_context_keys, ())
        self.assertEqual(first.missing_observed_context_keys, ())
        self.assertFalse(first.production_calibrated)
        self.assertFalse(first.execution_simulator_calibrated)
        self.assertEqual(first.live_trading_state, "HARD_LOCKED")
        self.assertEqual(first.profitability_state, "UNPROVEN")

    def test_non_broker_outcome_cannot_enter_calibration_set(self) -> None:
        paper = replace(
            self.outcomes[0],
            outcome_id="paper-outcome",
            order_id="order:paper-outcome",
            origin=EvidenceOrigin.PAPER,
            external_execution_id=None,
            raw_content_sha256=self.raw_sha("paper-outcome"),
        )
        self.ledger.append(paper)
        with self.assertRaisesRegex(
            InvariantViolation,
            "NON_OBSERVED_EVIDENCE_IN_CALIBRATION",
        ):
            self.build_report(
                outcome_ids=(
                    *(outcome.outcome_id for outcome in self.outcomes),
                    paper.outcome_id,
                )
            )

    def test_report_uses_latest_version_of_each_observed_outcome(self) -> None:
        original = self.outcomes[0]
        corrected = self.observed_outcome(
            original.outcome_id,
            original.context,
            version=2,
            fill_ratio="0.5",
            shortfall_bps="0",
            latency_ns=10,
        )
        self.ledger.append(corrected)
        report = self.build_report()
        self.assertIn(corrected.sha256(), report.observed_outcome_sha256s)
        self.assertNotIn(original.sha256(), report.observed_outcome_sha256s)

    def test_missing_prediction_and_observed_contexts_are_explicit(self) -> None:
        msft_context = self.execution_context(instrument_id="MSFT")
        msft_outcomes = self.append_observed_context(
            prefix="msft",
            context=msft_context,
        )
        missing_prediction = self.build_report(
            outcome_ids=(
                *(outcome.outcome_id for outcome in self.outcomes),
                *(outcome.outcome_id for outcome in msft_outcomes),
            )
        )
        self.assertFalse(missing_prediction.all_required_gaps_passed)
        self.assertEqual(
            missing_prediction.missing_prediction_context_keys,
            (msft_context.sha256(),),
        )

        surface_with_msft = PredictionSurface(
            surface_id="surface-with-msft",
            version=1,
            model_definition_sha256=self.definition.sha256(),
            model_id=self.definition.model_id,
            model_version=self.definition.version,
            predictions=(
                self.prediction,
                self.prediction_for(msft_context),
            ),
            created_at_ns=2_000,
        )
        missing_observed = self.build_report(surface=surface_with_msft)
        self.assertFalse(missing_observed.all_required_gaps_passed)
        self.assertEqual(
            missing_observed.missing_observed_context_keys,
            (msft_context.sha256(),),
        )

    def test_insufficient_observations_fail_each_family_without_aggregate_masking(self) -> None:
        report = self.build_report(
            outcome_ids=tuple(
                outcome.outcome_id for outcome in self.outcomes[:2]
            )
        )
        self.assertFalse(report.all_required_gaps_passed)
        self.assertEqual(len(report.context_gaps), 5)
        self.assertTrue(
            all(
                gap.status is GapStatus.INSUFFICIENT_OBSERVATIONS
                for gap in report.context_gaps
            )
        )

    def test_one_failed_family_blocks_report_even_when_others_pass(self) -> None:
        bad_prediction = self.prediction_for(
            self.context,
            prediction_id="bad-shortfall",
            shortfall_p50="100",
            shortfall_p95="120",
        )
        surface = PredictionSurface(
            surface_id="bad-shortfall-surface",
            version=1,
            model_definition_sha256=self.definition.sha256(),
            model_id=self.definition.model_id,
            model_version=self.definition.version,
            predictions=(bad_prediction,),
            created_at_ns=2_000,
        )
        report = self.build_report(surface=surface)
        by_family = {gap.family: gap for gap in report.context_gaps}
        self.assertEqual(
            by_family[RealityGapFamily.SHORTFALL_BPS].status,
            GapStatus.FAIL,
        )
        self.assertTrue(
            all(
                gap.status is GapStatus.PASS
                for family, gap in by_family.items()
                if family is not RealityGapFamily.SHORTFALL_BPS
            )
        )
        self.assertFalse(report.all_required_gaps_passed)

    def test_tolerance_surface_must_cover_every_family_exactly_once(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "MISSING_REALITY_GAP_TOLERANCE",
        ):
            self.build_report(tolerances=self.tolerances[:-1])
        with self.assertRaisesRegex(
            InvariantViolation,
            "DUPLICATE_REALITY_GAP_TOLERANCE",
        ):
            self.build_report(tolerances=(*self.tolerances, self.tolerances[0]))
        with self.assertRaisesRegex(
            InvariantViolation,
            "NEGATIVE_REALITY_GAP_TOLERANCE",
        ):
            replace(
                self.tolerances[0],
                max_p50_absolute_gap=Decimal("-1"),
            )

    def review(self, report, **overrides) -> CalibrationReview:
        values = dict(
            review_id="calibration-review-1",
            reviewer_id="independent-human",
            reviewer_role=DatasetRole.INDEPENDENT_EVALUATOR,
            report_sha256=report.sha256(),
            approved=True,
            human_approval_id="human-approval-1",
            minority_findings=(
                "Sparse stress-regime observations remain a concern",
            ),
            unresolved_findings=(),
            reviewed_at_ns=2_600,
        )
        values.update(overrides)
        return CalibrationReview(**values)

    def request(self, report, **overrides) -> CalibrationRequest:
        values = dict(
            request_id="calibration-request-1",
            challenger_model_id=self.definition.model_id,
            challenger_model_version=self.definition.version,
            model_definition_sha256=self.definition.sha256(),
            report_sha256=report.sha256(),
            requested_by_id="model-council",
            requested_by_role=DatasetRole.MODEL_COUNCIL,
            independent_review=self.review(report),
            rollback_plan="Retain incumbent and disable challenger predictions",
            requested_at_ns=2_700,
        )
        values.update(overrides)
        return CalibrationRequest(**values)

    def test_independent_gate_can_only_make_model_eligible_as_challenger(self) -> None:
        report = self.build_report()
        decision = CalibrationGate().evaluate(
            self.request(report),
            report,
            self.definition,
        )
        self.assertEqual(
            decision.state,
            CalibrationDecisionState.ELIGIBLE_AS_CHALLENGER,
        )
        self.assertEqual(decision.reasons, ())
        self.assertFalse(decision.production_calibrated)
        self.assertFalse(decision.execution_simulator_calibrated)
        self.assertFalse(decision.challenger_selected)
        self.assertEqual(decision.live_trading_state, "HARD_LOCKED")
        self.assertEqual(decision.decision_sha256, decision.recomputed_sha256())
        with self.assertRaises(ValueError):
            CalibrationDecisionState("PRODUCTION_CALIBRATED")

    def test_failed_gap_or_missing_context_blocks_challenger_gate(self) -> None:
        bad_prediction = self.prediction_for(
            self.context,
            prediction_id="bad-shortfall",
            shortfall_p50="100",
            shortfall_p95="120",
        )
        surface = PredictionSurface(
            surface_id="bad-surface",
            version=1,
            model_definition_sha256=self.definition.sha256(),
            model_id=self.definition.model_id,
            model_version=self.definition.version,
            predictions=(bad_prediction,),
            created_at_ns=2_000,
        )
        report = self.build_report(surface=surface)
        decision = CalibrationGate().evaluate(
            self.request(report),
            report,
            self.definition,
        )
        self.assertEqual(decision.state, CalibrationDecisionState.BLOCKED)
        self.assertIn("REALITY_GAP_FAILURE", decision.reasons)

    def test_review_must_be_independent_human_bound_and_have_rollback(self) -> None:
        report = self.build_report()
        cases = (
            (
                "INDEPENDENT_CALIBRATION_REVIEW_REQUIRED",
                self.request(
                    report,
                    independent_review=self.review(
                        report,
                        reviewer_id="model-council",
                        reviewer_role=DatasetRole.MODEL_COUNCIL,
                    ),
                ),
            ),
            (
                "CALIBRATION_HUMAN_APPROVAL_REQUIRED",
                self.request(
                    report,
                    independent_review=self.review(
                        report,
                        human_approval_id=None,
                    ),
                ),
            ),
            (
                "CALIBRATION_MINORITY_FINDINGS_REQUIRED",
                self.request(
                    report,
                    independent_review=self.review(
                        report,
                        minority_findings=(),
                    ),
                ),
            ),
            (
                "CALIBRATION_ROLLBACK_PLAN_REQUIRED",
                self.request(report, rollback_plan=None),
            ),
            (
                "CALIBRATION_REVIEW_REPORT_MISMATCH",
                self.request(
                    report,
                    independent_review=self.review(
                        report,
                        report_sha256="f" * 64,
                    ),
                ),
            ),
        )
        for reason, request in cases:
            with self.subTest(reason=reason):
                decision = CalibrationGate().evaluate(
                    request,
                    report,
                    self.definition,
                )
                self.assertEqual(
                    decision.state,
                    CalibrationDecisionState.BLOCKED,
                )
                self.assertIn(reason, decision.reasons)

    def test_model_must_be_declared_challenger_and_bind_exact_report(self) -> None:
        report = self.build_report()
        standalone = self.model_definition(challenger_of_model_id=None)
        decision = CalibrationGate().evaluate(
            self.request(report),
            report,
            standalone,
        )
        self.assertEqual(decision.state, CalibrationDecisionState.BLOCKED)
        self.assertIn("CHALLENGER_MODEL_REQUIRED", decision.reasons)

        mismatch = CalibrationGate().evaluate(
            self.request(report, report_sha256="f" * 64),
            report,
            self.definition,
        )
        self.assertIn("CALIBRATION_REPORT_MISMATCH", mismatch.reasons)


if __name__ == "__main__":
    unittest.main()
