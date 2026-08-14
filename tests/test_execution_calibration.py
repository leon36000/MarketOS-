from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest

from marketos.errors import InvariantViolation
from marketos.execution_calibration import (
    DistributionKind,
    ExecutionAssumptions,
    ExecutionFidelityStage,
    ExecutionInputCapability,
    FillModelDefinition,
    PredictedExecutionDistribution,
    PredictionSurface,
    QuantileDistribution,
)
from marketos.execution_evidence import ExecutionContext, Marketability
from marketos.orders import OrderSide, OrderType
from uuid import UUID


VENUE_ID = UUID("00000000-0000-0000-0000-000000012010")


class ExecutionCalibrationContractTests(unittest.TestCase):
    @staticmethod
    def assumptions(**overrides) -> ExecutionAssumptions:
        values = dict(
            marketability_rule="Classify against point-in-time best bid/ask",
            latency_model="Submission-to-ack and completion distributions by venue",
            spread_model="Pay quoted spread conditional on marketability",
            depth_model="Consume only visible point-in-time depth",
            participation_model="Cap participation by context bucket",
            queue_model="FIFO queue approximation with explicit uncertainty",
            partial_fill_model="Allow partial fills from available depth and queue",
            cancellation_model="Cancellation hazard conditional on latency and queue",
            reject_model="Reject probability by venue and order constraints",
            fee_model="Explicit venue, clearing and regulatory fee schedule",
            financing_model="Financing and borrow costs by holding horizon",
            opportunity_cost_model="Unfilled quantity marked to later reference price",
            impact_model="Temporary and permanent impact by participation and regime",
        )
        values.update(overrides)
        return ExecutionAssumptions(**values)

    @staticmethod
    def definition(**overrides) -> FillModelDefinition:
        values = dict(
            model_id="fill-model-l2",
            version=1,
            challenger_of_model_id=None,
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
            assumptions=ExecutionCalibrationContractTests.assumptions(),
            trained_through_ns=1_000,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            dependency_lock_sha256="c" * 64,
            production_calibrated=False,
        )
        values.update(overrides)
        return FillModelDefinition(**values)

    @staticmethod
    def context(
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

    def prediction(
        self,
        prediction_id: str,
        *,
        context: ExecutionContext | None = None,
        definition: FillModelDefinition | None = None,
    ) -> PredictedExecutionDistribution:
        definition = self.definition() if definition is None else definition
        return PredictedExecutionDistribution(
            prediction_id=prediction_id,
            model_id=definition.model_id,
            model_version=definition.version,
            model_definition_sha256=definition.sha256(),
            context=self.context() if context is None else context,
            as_of_ns=1_100,
            fill_ratio=self.distribution(
                DistributionKind.FILL_RATIO,
                "0.40",
                "0.75",
                "0.95",
            ),
            shortfall_bps=self.distribution(
                DistributionKind.SHORTFALL_BPS,
                "-1",
                "4",
                "15",
            ),
            latency_ns=self.distribution(
                DistributionKind.LATENCY_NS,
                "1000",
                "5000",
                "20000",
            ),
            cancellation_probability=self.distribution(
                DistributionKind.CANCELLATION_PROBABILITY,
                "0.01",
                "0.05",
                "0.15",
            ),
            reject_probability=self.distribution(
                DistributionKind.REJECT_PROBABILITY,
                "0.00",
                "0.01",
                "0.05",
            ),
        )

    def test_all_execution_assumptions_are_explicit_immutable_and_hash_stable(self) -> None:
        assumptions = self.assumptions()
        reordered = ExecutionAssumptions(
            **{
                key: assumptions.canonical_dict()[key]
                for key in reversed(tuple(assumptions.canonical_dict()))
            }
        )
        self.assertEqual(assumptions.sha256(), reordered.sha256())
        self.assertEqual(len(assumptions.canonical_dict()), 13)
        with self.assertRaises((AttributeError, TypeError)):
            assumptions.queue_model = "silent replacement"

    def test_each_missing_assumption_fails_closed(self) -> None:
        fields = tuple(self.assumptions().canonical_dict())
        for field in fields:
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    InvariantViolation,
                    f"MISSING_{field.upper()}",
                ):
                    self.assumptions(**{field: ""})

    def test_fidelity_stages_and_input_capabilities_are_contiguous(self) -> None:
        definition = self.definition()
        self.assertEqual(
            definition.claimed_fidelity_stage,
            ExecutionFidelityStage.S2_L2_DEPTH,
        )
        self.assertFalse(definition.production_calibrated)
        self.assertFalse(definition.execution_simulator_calibrated)
        self.assertEqual(definition.live_trading_state, "HARD_LOCKED")

        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_FIDELITY_STAGE_GAP"):
            self.definition(
                completed_fidelity_stages=(
                    ExecutionFidelityStage.S0_BAR,
                    ExecutionFidelityStage.S2_L2_DEPTH,
                )
            )
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_CAPABILITY_STAGE_MISMATCH"):
            self.definition(
                input_capabilities=(
                    ExecutionInputCapability.BARS,
                    ExecutionInputCapability.L2_DEPTH,
                    ExecutionInputCapability.TRADES_QUOTES,
                )
            )
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_FIDELITY_CLAIM_MISMATCH"):
            self.definition(
                claimed_fidelity_stage=ExecutionFidelityStage.S3_L3_QUEUE,
            )

    def test_production_calibration_cannot_be_claimed_by_local_definition(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "PRODUCTION_EXECUTION_CALIBRATION_FORBIDDEN",
        ):
            self.definition(production_calibrated=True)

    def test_definition_version_hashes_and_challenger_identity_are_strict(self) -> None:
        definition = self.definition()
        self.assertEqual(definition.sha256(), definition.sha256())
        challenger = self.definition(
            model_id="fill-model-l2-challenger",
            challenger_of_model_id=definition.model_id,
        )
        self.assertEqual(challenger.challenger_of_model_id, definition.model_id)
        with self.assertRaisesRegex(InvariantViolation, "INVALID_FILL_MODEL_CODE_SHA256"):
            self.definition(code_sha256="bad")
        with self.assertRaisesRegex(InvariantViolation, "FILL_MODEL_CANNOT_CHALLENGE_SELF"):
            self.definition(challenger_of_model_id="fill-model-l2")

    def test_quantiles_are_ordered_and_contextually_bounded(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "INVALID_EXECUTION_QUANTILES"):
            self.distribution(
                DistributionKind.SHORTFALL_BPS,
                "10",
                "5",
                "20",
            )
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_PROBABILITY_OUT_OF_RANGE"):
            self.distribution(
                DistributionKind.FILL_RATIO,
                "0.1",
                "0.5",
                "1.1",
            )
        with self.assertRaisesRegex(InvariantViolation, "NEGATIVE_EXECUTION_LATENCY"):
            self.distribution(
                DistributionKind.LATENCY_NS,
                "-1",
                "5",
                "20",
            )
        with self.assertRaisesRegex(InvariantViolation, "INSUFFICIENT_EXECUTION_DISTRIBUTION_SAMPLES"):
            self.distribution(
                DistributionKind.SHORTFALL_BPS,
                "-1",
                "5",
                "20",
                sample_count=1,
            )
        signed = self.distribution(
            DistributionKind.SHORTFALL_BPS,
            "-5",
            "0",
            "10",
        )
        self.assertEqual(signed.p05, Decimal("-5"))

    def test_prediction_requires_exact_metric_kinds_and_model_binding(self) -> None:
        prediction = self.prediction("prediction-1")
        self.assertEqual(prediction.fill_ratio.kind, DistributionKind.FILL_RATIO)
        self.assertEqual(prediction.context.instrument_id, "AAPL")
        self.assertEqual(prediction.sha256(), prediction.sha256())
        with self.assertRaisesRegex(InvariantViolation, "PREDICTION_METRIC_KIND_MISMATCH"):
            replace(
                prediction,
                fill_ratio=self.distribution(
                    DistributionKind.SHORTFALL_BPS,
                    "0",
                    "1",
                    "2",
                ),
            )
        with self.assertRaisesRegex(InvariantViolation, "INVALID_MODEL_DEFINITION_SHA256"):
            replace(prediction, model_definition_sha256="bad")

    def test_prediction_surface_is_deterministic_and_rejects_duplicate_contexts(self) -> None:
        definition = self.definition()
        first_prediction = self.prediction(
            "p-aapl",
            context=self.context(instrument_id="AAPL"),
            definition=definition,
        )
        second_prediction = self.prediction(
            "p-msft",
            context=self.context(instrument_id="MSFT"),
            definition=definition,
        )
        first = PredictionSurface(
            surface_id="surface-1",
            version=1,
            model_definition_sha256=definition.sha256(),
            model_id=definition.model_id,
            model_version=definition.version,
            predictions=(second_prediction, first_prediction),
            created_at_ns=1_200,
        )
        second = PredictionSurface(
            surface_id="surface-1",
            version=1,
            model_definition_sha256=definition.sha256(),
            model_id=definition.model_id,
            model_version=definition.version,
            predictions=(first_prediction, second_prediction),
            created_at_ns=1_200,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.input_root_sha256, second.input_root_sha256)
        self.assertEqual(first.sha256(), second.sha256())
        with self.assertRaisesRegex(InvariantViolation, "DUPLICATE_EXECUTION_PREDICTION_CONTEXT"):
            PredictionSurface(
                surface_id="duplicate-context",
                version=1,
                model_definition_sha256=definition.sha256(),
                model_id=definition.model_id,
                model_version=definition.version,
                predictions=(first_prediction, replace(first_prediction, prediction_id="other")),
                created_at_ns=1_200,
            )

    def test_surface_rejects_prediction_from_different_model_or_definition(self) -> None:
        definition = self.definition()
        prediction = self.prediction("prediction-1", definition=definition)
        with self.assertRaisesRegex(InvariantViolation, "PREDICTION_MODEL_BINDING_MISMATCH"):
            PredictionSurface(
                surface_id="bad-model",
                version=1,
                model_definition_sha256=definition.sha256(),
                model_id=definition.model_id,
                model_version=definition.version,
                predictions=(replace(prediction, model_id="other-model"),),
                created_at_ns=1_200,
            )


if __name__ == "__main__":
    unittest.main()
