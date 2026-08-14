"""Explicit execution-model assumptions and contextual prediction surfaces.

This module defines provider-neutral fill-model contracts.  It deliberately
stops short of calibration authority: local definitions and predictions cannot
mark a production simulator calibrated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import re
from typing import Iterable

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .execution_evidence import (
    EvidenceOrigin,
    ExecutionContext,
    ExecutionEvidenceLedger,
    ExecutionOutcome,
)
from .experiments import DatasetRole

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _identifier(value: str, code: str) -> str:
    normalized = _text(value, code)
    if not _SAFE_ID.fullmatch(normalized):
        raise InvariantViolation(code)
    return normalized


def _positive_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvariantViolation(code)
    return value


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _digest(value: str, code: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise InvariantViolation(code)
    return value


def _decimal(value: Decimal, code: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(code)
    return value


class ExecutionFidelityStage(str, Enum):
    S0_BAR = "S0_BAR"
    S1_TRADE_QUOTE = "S1_TRADE_QUOTE"
    S2_L2_DEPTH = "S2_L2_DEPTH"
    S3_L3_QUEUE = "S3_L3_QUEUE"
    S4_BROKER_SIMULATOR = "S4_BROKER_SIMULATOR"
    S5_SHADOW_PAPER_BROKER_COMPARISON = (
        "S5_SHADOW_PAPER_BROKER_COMPARISON"
    )


class ExecutionInputCapability(str, Enum):
    BARS = "BARS"
    TRADES_QUOTES = "TRADES_QUOTES"
    L2_DEPTH = "L2_DEPTH"
    L3_QUEUE = "L3_QUEUE"
    BROKER_RULES = "BROKER_RULES"
    SHADOW_PAPER_BROKER_COMPARISON = "SHADOW_PAPER_BROKER_COMPARISON"


_FIDELITY_ORDER = (
    ExecutionFidelityStage.S0_BAR,
    ExecutionFidelityStage.S1_TRADE_QUOTE,
    ExecutionFidelityStage.S2_L2_DEPTH,
    ExecutionFidelityStage.S3_L3_QUEUE,
    ExecutionFidelityStage.S4_BROKER_SIMULATOR,
    ExecutionFidelityStage.S5_SHADOW_PAPER_BROKER_COMPARISON,
)

_CAPABILITY_ORDER = (
    ExecutionInputCapability.BARS,
    ExecutionInputCapability.TRADES_QUOTES,
    ExecutionInputCapability.L2_DEPTH,
    ExecutionInputCapability.L3_QUEUE,
    ExecutionInputCapability.BROKER_RULES,
    ExecutionInputCapability.SHADOW_PAPER_BROKER_COMPARISON,
)


@dataclass(frozen=True, slots=True)
class ExecutionAssumptions:
    marketability_rule: str
    latency_model: str
    spread_model: str
    depth_model: str
    participation_model: str
    queue_model: str
    partial_fill_model: str
    cancellation_model: str
    reject_model: str
    fee_model: str
    financing_model: str
    opportunity_cost_model: str
    impact_model: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(
                self,
                field_name,
                _text(
                    getattr(self, field_name),
                    f"MISSING_{field_name.upper()}",
                ),
            )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "marketability_rule": self.marketability_rule,
            "latency_model": self.latency_model,
            "spread_model": self.spread_model,
            "depth_model": self.depth_model,
            "participation_model": self.participation_model,
            "queue_model": self.queue_model,
            "partial_fill_model": self.partial_fill_model,
            "cancellation_model": self.cancellation_model,
            "reject_model": self.reject_model,
            "fee_model": self.fee_model,
            "financing_model": self.financing_model,
            "opportunity_cost_model": self.opportunity_cost_model,
            "impact_model": self.impact_model,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class FillModelDefinition:
    model_id: str
    version: int
    challenger_of_model_id: str | None
    completed_fidelity_stages: tuple[ExecutionFidelityStage, ...]
    claimed_fidelity_stage: ExecutionFidelityStage
    input_capabilities: tuple[ExecutionInputCapability, ...]
    assumptions: ExecutionAssumptions
    trained_through_ns: int
    code_sha256: str
    config_sha256: str
    dependency_lock_sha256: str
    production_calibrated: bool = False
    execution_simulator_calibrated: bool = False
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        model_id = _identifier(self.model_id, "INVALID_FILL_MODEL_ID")
        object.__setattr__(self, "model_id", model_id)
        _positive_int(self.version, "INVALID_FILL_MODEL_VERSION")
        challenger = self.challenger_of_model_id
        if challenger is not None:
            challenger = _identifier(
                challenger,
                "INVALID_CHALLENGER_MODEL_ID",
            )
            if challenger == model_id:
                raise InvariantViolation("FILL_MODEL_CANNOT_CHALLENGE_SELF")
            object.__setattr__(self, "challenger_of_model_id", challenger)
        stages = tuple(self.completed_fidelity_stages)
        if not stages or any(
            not isinstance(stage, ExecutionFidelityStage) for stage in stages
        ):
            raise InvariantViolation("MISSING_EXECUTION_FIDELITY_STAGES")
        if stages != _FIDELITY_ORDER[: len(stages)]:
            raise InvariantViolation("EXECUTION_FIDELITY_STAGE_GAP")
        object.__setattr__(self, "completed_fidelity_stages", stages)
        if not isinstance(
            self.claimed_fidelity_stage,
            ExecutionFidelityStage,
        ):
            raise InvariantViolation("INVALID_EXECUTION_FIDELITY_CLAIM")
        if self.claimed_fidelity_stage is not stages[-1]:
            raise InvariantViolation("EXECUTION_FIDELITY_CLAIM_MISMATCH")
        capabilities = tuple(self.input_capabilities)
        if capabilities != _CAPABILITY_ORDER[: len(stages)]:
            raise InvariantViolation("EXECUTION_CAPABILITY_STAGE_MISMATCH")
        object.__setattr__(self, "input_capabilities", capabilities)
        if not isinstance(self.assumptions, ExecutionAssumptions):
            raise InvariantViolation("EXECUTION_ASSUMPTIONS_REQUIRED")
        _nonnegative_int(
            self.trained_through_ns,
            "INVALID_FILL_MODEL_TRAINING_CUTOFF",
        )
        _digest(self.code_sha256, "INVALID_FILL_MODEL_CODE_SHA256")
        _digest(self.config_sha256, "INVALID_FILL_MODEL_CONFIG_SHA256")
        _digest(
            self.dependency_lock_sha256,
            "INVALID_FILL_MODEL_DEPENDENCY_SHA256",
        )
        if self.production_calibrated is not False:
            raise InvariantViolation(
                "PRODUCTION_EXECUTION_CALIBRATION_FORBIDDEN"
            )
        if self.execution_simulator_calibrated is not False:
            raise InvariantViolation(
                "EXECUTION_SIMULATOR_CALIBRATION_FORBIDDEN"
            )
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("FILL_MODEL_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("FILL_MODEL_CANNOT_PROVE_PROFITABILITY")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "challenger_of_model_id": self.challenger_of_model_id,
            "completed_fidelity_stages": self.completed_fidelity_stages,
            "claimed_fidelity_stage": self.claimed_fidelity_stage,
            "input_capabilities": self.input_capabilities,
            "assumptions": self.assumptions,
            "trained_through_ns": self.trained_through_ns,
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "production_calibrated": self.production_calibrated,
            "execution_simulator_calibrated": (
                self.execution_simulator_calibrated
            ),
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class DistributionKind(str, Enum):
    FILL_RATIO = "FILL_RATIO"
    SHORTFALL_BPS = "SHORTFALL_BPS"
    LATENCY_NS = "LATENCY_NS"
    CANCELLATION_PROBABILITY = "CANCELLATION_PROBABILITY"
    REJECT_PROBABILITY = "REJECT_PROBABILITY"


_PROBABILITY_KINDS = {
    DistributionKind.FILL_RATIO,
    DistributionKind.CANCELLATION_PROBABILITY,
    DistributionKind.REJECT_PROBABILITY,
}


@dataclass(frozen=True, slots=True)
class QuantileDistribution:
    kind: DistributionKind
    p05: Decimal
    p50: Decimal
    p95: Decimal
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DistributionKind):
            raise InvariantViolation("INVALID_EXECUTION_DISTRIBUTION_KIND")
        p05 = _decimal(self.p05, "INVALID_EXECUTION_QUANTILE")
        p50 = _decimal(self.p50, "INVALID_EXECUTION_QUANTILE")
        p95 = _decimal(self.p95, "INVALID_EXECUTION_QUANTILE")
        if not p05 <= p50 <= p95:
            raise InvariantViolation("INVALID_EXECUTION_QUANTILES")
        if self.kind in _PROBABILITY_KINDS and not (
            Decimal("0") <= p05 <= p50 <= p95 <= Decimal("1")
        ):
            raise InvariantViolation("EXECUTION_PROBABILITY_OUT_OF_RANGE")
        if self.kind is DistributionKind.LATENCY_NS and p05 < 0:
            raise InvariantViolation("NEGATIVE_EXECUTION_LATENCY")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 2
        ):
            raise InvariantViolation(
                "INSUFFICIENT_EXECUTION_DISTRIBUTION_SAMPLES"
            )
        object.__setattr__(self, "p05", p05)
        object.__setattr__(self, "p50", p50)
        object.__setattr__(self, "p95", p95)

    @property
    def unit(self) -> str:
        return {
            DistributionKind.FILL_RATIO: "RATIO",
            DistributionKind.SHORTFALL_BPS: "BPS",
            DistributionKind.LATENCY_NS: "NS",
            DistributionKind.CANCELLATION_PROBABILITY: "PROBABILITY",
            DistributionKind.REJECT_PROBABILITY: "PROBABILITY",
        }[self.kind]

    def canonical_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "unit": self.unit,
            "p05": self.p05,
            "p50": self.p50,
            "p95": self.p95,
            "sample_count": self.sample_count,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class PredictedExecutionDistribution:
    prediction_id: str
    model_id: str
    model_version: int
    model_definition_sha256: str
    context: ExecutionContext
    as_of_ns: int
    fill_ratio: QuantileDistribution
    shortfall_bps: QuantileDistribution
    latency_ns: QuantileDistribution
    cancellation_probability: QuantileDistribution
    reject_probability: QuantileDistribution
    live_trading_state: str = "HARD_LOCKED"
    production_calibrated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prediction_id",
            _identifier(self.prediction_id, "INVALID_EXECUTION_PREDICTION_ID"),
        )
        object.__setattr__(
            self,
            "model_id",
            _identifier(self.model_id, "INVALID_FILL_MODEL_ID"),
        )
        _positive_int(self.model_version, "INVALID_FILL_MODEL_VERSION")
        _digest(
            self.model_definition_sha256,
            "INVALID_MODEL_DEFINITION_SHA256",
        )
        if not isinstance(self.context, ExecutionContext):
            raise InvariantViolation("INVALID_EXECUTION_CONTEXT")
        _nonnegative_int(self.as_of_ns, "INVALID_EXECUTION_PREDICTION_TIME")
        expected = (
            (self.fill_ratio, DistributionKind.FILL_RATIO),
            (self.shortfall_bps, DistributionKind.SHORTFALL_BPS),
            (self.latency_ns, DistributionKind.LATENCY_NS),
            (
                self.cancellation_probability,
                DistributionKind.CANCELLATION_PROBABILITY,
            ),
            (self.reject_probability, DistributionKind.REJECT_PROBABILITY),
        )
        for distribution, kind in expected:
            if (
                not isinstance(distribution, QuantileDistribution)
                or distribution.kind is not kind
            ):
                raise InvariantViolation("PREDICTION_METRIC_KIND_MISMATCH")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("PREDICTION_CANNOT_CHANGE_LIVE_LOCK")
        if self.production_calibrated is not False:
            raise InvariantViolation(
                "PRODUCTION_EXECUTION_CALIBRATION_FORBIDDEN"
            )

    @property
    def context_key(self) -> str:
        return self.context.sha256()

    def canonical_dict(self) -> dict[str, object]:
        return {
            "prediction_id": self.prediction_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_definition_sha256": self.model_definition_sha256,
            "context": self.context,
            "as_of_ns": self.as_of_ns,
            "fill_ratio": self.fill_ratio,
            "shortfall_bps": self.shortfall_bps,
            "latency_ns": self.latency_ns,
            "cancellation_probability": self.cancellation_probability,
            "reject_probability": self.reject_probability,
            "live_trading_state": self.live_trading_state,
            "production_calibrated": self.production_calibrated,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class PredictionSurface:
    surface_id: str
    version: int
    model_definition_sha256: str
    model_id: str
    model_version: int
    predictions: tuple[PredictedExecutionDistribution, ...]
    created_at_ns: int
    input_root_sha256: str = field(init=False)
    live_trading_state: str = "HARD_LOCKED"
    production_calibrated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "surface_id",
            _identifier(self.surface_id, "INVALID_PREDICTION_SURFACE_ID"),
        )
        _positive_int(self.version, "INVALID_PREDICTION_SURFACE_VERSION")
        definition_sha = _digest(
            self.model_definition_sha256,
            "INVALID_MODEL_DEFINITION_SHA256",
        )
        model_id = _identifier(self.model_id, "INVALID_FILL_MODEL_ID")
        object.__setattr__(self, "model_id", model_id)
        _positive_int(self.model_version, "INVALID_FILL_MODEL_VERSION")
        predictions = tuple(self.predictions)
        if not predictions:
            raise InvariantViolation("EMPTY_EXECUTION_PREDICTION_SURFACE")
        for prediction in predictions:
            if not isinstance(prediction, PredictedExecutionDistribution):
                raise InvariantViolation("INVALID_EXECUTION_PREDICTION")
            if (
                prediction.model_id != model_id
                or prediction.model_version != self.model_version
                or prediction.model_definition_sha256 != definition_sha
            ):
                raise InvariantViolation("PREDICTION_MODEL_BINDING_MISMATCH")
        contexts = [prediction.context_key for prediction in predictions]
        if len(contexts) != len(set(contexts)):
            raise InvariantViolation(
                "DUPLICATE_EXECUTION_PREDICTION_CONTEXT"
            )
        ordered = tuple(
            sorted(
                predictions,
                key=lambda prediction: (
                    prediction.context_key,
                    prediction.prediction_id,
                ),
            )
        )
        object.__setattr__(self, "predictions", ordered)
        _nonnegative_int(self.created_at_ns, "INVALID_PREDICTION_SURFACE_TIME")
        object.__setattr__(
            self,
            "input_root_sha256",
            canonical_sha256(tuple(prediction.sha256() for prediction in ordered)),
        )
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation(
                "PREDICTION_SURFACE_CANNOT_CHANGE_LIVE_LOCK"
            )
        if self.production_calibrated is not False:
            raise InvariantViolation(
                "PRODUCTION_EXECUTION_CALIBRATION_FORBIDDEN"
            )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "version": self.version,
            "model_definition_sha256": self.model_definition_sha256,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "predictions": self.predictions,
            "created_at_ns": self.created_at_ns,
            "input_root_sha256": self.input_root_sha256,
            "live_trading_state": self.live_trading_state,
            "production_calibrated": self.production_calibrated,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())



class RealityGapFamily(str, Enum):
    FILL_RATIO = "FILL_RATIO"
    SHORTFALL_BPS = "SHORTFALL_BPS"
    LATENCY_NS = "LATENCY_NS"
    CANCELLATION_RATE = "CANCELLATION_RATE"
    REJECT_RATE = "REJECT_RATE"


_REALITY_GAP_ORDER = (
    RealityGapFamily.FILL_RATIO,
    RealityGapFamily.SHORTFALL_BPS,
    RealityGapFamily.LATENCY_NS,
    RealityGapFamily.CANCELLATION_RATE,
    RealityGapFamily.REJECT_RATE,
)

_REALITY_GAP_KIND = {
    RealityGapFamily.FILL_RATIO: DistributionKind.FILL_RATIO,
    RealityGapFamily.SHORTFALL_BPS: DistributionKind.SHORTFALL_BPS,
    RealityGapFamily.LATENCY_NS: DistributionKind.LATENCY_NS,
    RealityGapFamily.CANCELLATION_RATE: (
        DistributionKind.CANCELLATION_PROBABILITY
    ),
    RealityGapFamily.REJECT_RATE: DistributionKind.REJECT_PROBABILITY,
}


class GapStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"


@dataclass(frozen=True, slots=True)
class CalibrationTolerance:
    family: RealityGapFamily
    max_p50_absolute_gap: Decimal
    max_p95_absolute_gap: Decimal
    min_observations: int

    def __post_init__(self) -> None:
        if not isinstance(self.family, RealityGapFamily):
            raise InvariantViolation("INVALID_REALITY_GAP_FAMILY")
        p50 = _decimal(
            self.max_p50_absolute_gap,
            "INVALID_REALITY_GAP_TOLERANCE",
        )
        p95 = _decimal(
            self.max_p95_absolute_gap,
            "INVALID_REALITY_GAP_TOLERANCE",
        )
        if p50 < 0 or p95 < 0:
            raise InvariantViolation("NEGATIVE_REALITY_GAP_TOLERANCE")
        if (
            isinstance(self.min_observations, bool)
            or not isinstance(self.min_observations, int)
            or self.min_observations < 2
        ):
            raise InvariantViolation("INVALID_CALIBRATION_MIN_OBSERVATIONS")
        object.__setattr__(self, "max_p50_absolute_gap", p50)
        object.__setattr__(self, "max_p95_absolute_gap", p95)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "max_p50_absolute_gap": self.max_p50_absolute_gap,
            "max_p95_absolute_gap": self.max_p95_absolute_gap,
            "min_observations": self.min_observations,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ContextRealityGap:
    context: ExecutionContext
    family: RealityGapFamily
    predicted_distribution: QuantileDistribution
    observed_distribution: QuantileDistribution | None
    p50_absolute_gap: Decimal | None
    p95_absolute_gap: Decimal | None
    tolerance_sha256: str
    observation_count: int
    status: GapStatus
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.context, ExecutionContext):
            raise InvariantViolation("INVALID_REALITY_GAP_CONTEXT")
        if not isinstance(self.family, RealityGapFamily):
            raise InvariantViolation("INVALID_REALITY_GAP_FAMILY")
        expected_kind = _REALITY_GAP_KIND[self.family]
        if (
            not isinstance(
                self.predicted_distribution,
                QuantileDistribution,
            )
            or self.predicted_distribution.kind is not expected_kind
        ):
            raise InvariantViolation("REALITY_GAP_PREDICTION_KIND_MISMATCH")
        if self.observed_distribution is not None and (
            not isinstance(self.observed_distribution, QuantileDistribution)
            or self.observed_distribution.kind is not expected_kind
        ):
            raise InvariantViolation("REALITY_GAP_OBSERVED_KIND_MISMATCH")
        if (
            isinstance(self.observation_count, bool)
            or not isinstance(self.observation_count, int)
            or self.observation_count < 0
        ):
            raise InvariantViolation("INVALID_REALITY_GAP_OBSERVATION_COUNT")
        _digest(self.tolerance_sha256, "INVALID_CALIBRATION_TOLERANCE_SHA256")
        if not isinstance(self.status, GapStatus):
            raise InvariantViolation("INVALID_REALITY_GAP_STATUS")
        reasons = tuple(_text(reason, "INVALID_REALITY_GAP_REASON") for reason in self.reasons)
        if len(reasons) != len(set(reasons)):
            raise InvariantViolation("DUPLICATE_REALITY_GAP_REASON")
        object.__setattr__(self, "reasons", reasons)
        if self.status is GapStatus.PASS:
            if reasons:
                raise InvariantViolation("PASSING_REALITY_GAP_HAS_REASONS")
            if (
                self.observed_distribution is None
                or self.p50_absolute_gap is None
                or self.p95_absolute_gap is None
            ):
                raise InvariantViolation("PASSING_REALITY_GAP_INCOMPLETE")
        else:
            if not reasons:
                raise InvariantViolation("FAILED_REALITY_GAP_REQUIRES_REASON")
        for value in (self.p50_absolute_gap, self.p95_absolute_gap):
            if value is not None:
                parsed = _decimal(value, "INVALID_REALITY_GAP_VALUE")
                if parsed < 0:
                    raise InvariantViolation("NEGATIVE_REALITY_GAP_VALUE")

    @property
    def context_key(self) -> str:
        return self.context.sha256()

    def canonical_dict(self) -> dict[str, object]:
        return {
            "context": self.context,
            "context_key": self.context_key,
            "family": self.family,
            "predicted_distribution": self.predicted_distribution,
            "observed_distribution": self.observed_distribution,
            "p50_absolute_gap": self.p50_absolute_gap,
            "p95_absolute_gap": self.p95_absolute_gap,
            "tolerance_sha256": self.tolerance_sha256,
            "observation_count": self.observation_count,
            "status": self.status,
            "reasons": self.reasons,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    report_id: str
    version: int
    model_id: str
    model_version: int
    model_definition_sha256: str
    prediction_surface_sha256: str
    observed_outcome_sha256s: tuple[str, ...]
    observed_evidence_root_sha256: str
    tolerance_sha256s: tuple[str, ...]
    context_gaps: tuple[ContextRealityGap, ...]
    missing_prediction_context_keys: tuple[str, ...]
    missing_observed_context_keys: tuple[str, ...]
    created_at_ns: int
    all_required_gaps_passed: bool
    production_calibrated: bool = False
    execution_simulator_calibrated: bool = False
    challenger_selected: bool = False
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "report_id",
            _identifier(self.report_id, "INVALID_CALIBRATION_REPORT_ID"),
        )
        _positive_int(self.version, "INVALID_CALIBRATION_REPORT_VERSION")
        object.__setattr__(
            self,
            "model_id",
            _identifier(self.model_id, "INVALID_FILL_MODEL_ID"),
        )
        _positive_int(self.model_version, "INVALID_FILL_MODEL_VERSION")
        _digest(
            self.model_definition_sha256,
            "INVALID_MODEL_DEFINITION_SHA256",
        )
        _digest(
            self.prediction_surface_sha256,
            "INVALID_PREDICTION_SURFACE_SHA256",
        )
        outcomes = tuple(self.observed_outcome_sha256s)
        if not outcomes or any(not _HEX64.fullmatch(value) for value in outcomes):
            raise InvariantViolation("INVALID_OBSERVED_OUTCOME_SHA256")
        if len(outcomes) != len(set(outcomes)):
            raise InvariantViolation("DUPLICATE_OBSERVED_OUTCOME_SHA256")
        ordered_outcomes = tuple(sorted(outcomes))
        object.__setattr__(self, "observed_outcome_sha256s", ordered_outcomes)
        expected_root = canonical_sha256(ordered_outcomes)
        if self.observed_evidence_root_sha256 != expected_root:
            raise InvariantViolation("OBSERVED_EVIDENCE_ROOT_MISMATCH")
        tolerances = tuple(self.tolerance_sha256s)
        if len(tolerances) != len(_REALITY_GAP_ORDER) or any(
            not _HEX64.fullmatch(value) for value in tolerances
        ):
            raise InvariantViolation("INVALID_CALIBRATION_TOLERANCE_SET")
        if len(tolerances) != len(set(tolerances)):
            raise InvariantViolation("DUPLICATE_CALIBRATION_TOLERANCE_SHA256")
        object.__setattr__(self, "tolerance_sha256s", tolerances)
        gaps = tuple(
            sorted(
                self.context_gaps,
                key=lambda gap: (
                    gap.context_key,
                    _REALITY_GAP_ORDER.index(gap.family),
                ),
            )
        )
        if any(not isinstance(gap, ContextRealityGap) for gap in gaps):
            raise InvariantViolation("INVALID_CONTEXT_REALITY_GAP")
        gap_keys = [(gap.context_key, gap.family) for gap in gaps]
        if len(gap_keys) != len(set(gap_keys)):
            raise InvariantViolation("DUPLICATE_CONTEXT_REALITY_GAP")
        object.__setattr__(self, "context_gaps", gaps)
        missing_prediction = tuple(sorted(self.missing_prediction_context_keys))
        missing_observed = tuple(sorted(self.missing_observed_context_keys))
        for values, code in (
            (missing_prediction, "INVALID_MISSING_PREDICTION_CONTEXT"),
            (missing_observed, "INVALID_MISSING_OBSERVED_CONTEXT"),
        ):
            if len(values) != len(set(values)) or any(
                not _HEX64.fullmatch(value) for value in values
            ):
                raise InvariantViolation(code)
        object.__setattr__(
            self,
            "missing_prediction_context_keys",
            missing_prediction,
        )
        object.__setattr__(
            self,
            "missing_observed_context_keys",
            missing_observed,
        )
        _nonnegative_int(self.created_at_ns, "INVALID_CALIBRATION_REPORT_TIME")
        expected_pass = (
            bool(gaps)
            and not missing_prediction
            and not missing_observed
            and all(gap.status is GapStatus.PASS for gap in gaps)
        )
        if self.all_required_gaps_passed is not expected_pass:
            raise InvariantViolation("CALIBRATION_REPORT_PASS_STATE_MISMATCH")
        if self.production_calibrated is not False:
            raise InvariantViolation(
                "PRODUCTION_EXECUTION_CALIBRATION_FORBIDDEN"
            )
        if self.execution_simulator_calibrated is not False:
            raise InvariantViolation(
                "EXECUTION_SIMULATOR_CALIBRATION_FORBIDDEN"
            )
        if self.challenger_selected is not False:
            raise InvariantViolation("CHALLENGER_SELECTION_FORBIDDEN")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("CALIBRATION_REPORT_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("CALIBRATION_REPORT_CANNOT_PROVE_PROFITABILITY")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "version": self.version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_definition_sha256": self.model_definition_sha256,
            "prediction_surface_sha256": self.prediction_surface_sha256,
            "observed_outcome_sha256s": self.observed_outcome_sha256s,
            "observed_evidence_root_sha256": (
                self.observed_evidence_root_sha256
            ),
            "tolerance_sha256s": self.tolerance_sha256s,
            "context_gaps": self.context_gaps,
            "missing_prediction_context_keys": (
                self.missing_prediction_context_keys
            ),
            "missing_observed_context_keys": (
                self.missing_observed_context_keys
            ),
            "created_at_ns": self.created_at_ns,
            "all_required_gaps_passed": self.all_required_gaps_passed,
            "production_calibrated": self.production_calibrated,
            "execution_simulator_calibrated": (
                self.execution_simulator_calibrated
            ),
            "challenger_selected": self.challenger_selected,
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def assert_integrity(self) -> None:
        rebuilt_gaps = tuple(
            ContextRealityGap(
                context=gap.context,
                family=gap.family,
                predicted_distribution=gap.predicted_distribution,
                observed_distribution=gap.observed_distribution,
                p50_absolute_gap=gap.p50_absolute_gap,
                p95_absolute_gap=gap.p95_absolute_gap,
                tolerance_sha256=gap.tolerance_sha256,
                observation_count=gap.observation_count,
                status=gap.status,
                reasons=gap.reasons,
            )
            for gap in self.context_gaps
        )
        CalibrationReport(
            report_id=self.report_id,
            version=self.version,
            model_id=self.model_id,
            model_version=self.model_version,
            model_definition_sha256=self.model_definition_sha256,
            prediction_surface_sha256=self.prediction_surface_sha256,
            observed_outcome_sha256s=self.observed_outcome_sha256s,
            observed_evidence_root_sha256=self.observed_evidence_root_sha256,
            tolerance_sha256s=self.tolerance_sha256s,
            context_gaps=rebuilt_gaps,
            missing_prediction_context_keys=(
                self.missing_prediction_context_keys
            ),
            missing_observed_context_keys=self.missing_observed_context_keys,
            created_at_ns=self.created_at_ns,
            all_required_gaps_passed=self.all_required_gaps_passed,
            production_calibrated=self.production_calibrated,
            execution_simulator_calibrated=(
                self.execution_simulator_calibrated
            ),
            challenger_selected=self.challenger_selected,
            live_trading_state=self.live_trading_state,
            profitability_state=self.profitability_state,
        )


def _nearest_rank(values: Iterable[Decimal], percentile: int) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise InvariantViolation("EMPTY_OBSERVED_EXECUTION_DISTRIBUTION")
    rank = max(1, (percentile * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def _observed_distribution(
    kind: DistributionKind,
    values: tuple[Decimal, ...],
) -> QuantileDistribution | None:
    if len(values) < 2:
        return None
    return QuantileDistribution(
        kind=kind,
        p05=_nearest_rank(values, 5),
        p50=_nearest_rank(values, 50),
        p95=_nearest_rank(values, 95),
        sample_count=len(values),
    )


def _predicted_distribution(
    prediction: PredictedExecutionDistribution,
    family: RealityGapFamily,
) -> QuantileDistribution:
    return {
        RealityGapFamily.FILL_RATIO: prediction.fill_ratio,
        RealityGapFamily.SHORTFALL_BPS: prediction.shortfall_bps,
        RealityGapFamily.LATENCY_NS: prediction.latency_ns,
        RealityGapFamily.CANCELLATION_RATE: (
            prediction.cancellation_probability
        ),
        RealityGapFamily.REJECT_RATE: prediction.reject_probability,
    }[family]


def _observed_values(
    outcomes: tuple[ExecutionOutcome, ...],
    family: RealityGapFamily,
) -> tuple[Decimal, ...]:
    if family is RealityGapFamily.FILL_RATIO:
        return tuple(outcome.fill_ratio for outcome in outcomes)
    if family is RealityGapFamily.SHORTFALL_BPS:
        return tuple(
            value
            for outcome in outcomes
            if (value := outcome.implementation_shortfall_bps) is not None
        )
    if family is RealityGapFamily.LATENCY_NS:
        return tuple(
            Decimal(outcome.completion_latency_ns) for outcome in outcomes
        )
    if family is RealityGapFamily.CANCELLATION_RATE:
        return tuple(
            Decimal(1 if outcome.cancelled else 0) for outcome in outcomes
        )
    return tuple(
        Decimal(1 if outcome.rejected else 0) for outcome in outcomes
    )


def build_reality_gap_report(
    *,
    report_id: str,
    version: int,
    model_definition: FillModelDefinition,
    prediction_surface: PredictionSurface,
    evidence_ledger: ExecutionEvidenceLedger,
    observed_outcome_ids: tuple[str, ...],
    tolerances: tuple[CalibrationTolerance, ...],
    created_at_ns: int,
) -> CalibrationReport:
    if not isinstance(model_definition, FillModelDefinition):
        raise InvariantViolation("FILL_MODEL_DEFINITION_REQUIRED")
    if not isinstance(prediction_surface, PredictionSurface):
        raise InvariantViolation("PREDICTION_SURFACE_REQUIRED")
    model_sha = model_definition.sha256()
    if (
        prediction_surface.model_definition_sha256 != model_sha
        or prediction_surface.model_id != model_definition.model_id
        or prediction_surface.model_version != model_definition.version
    ):
        raise InvariantViolation("PREDICTION_SURFACE_MODEL_BINDING_MISMATCH")
    outcome_ids = tuple(
        _identifier(value, "INVALID_CALIBRATION_OUTCOME_ID")
        for value in observed_outcome_ids
    )
    if not outcome_ids:
        raise InvariantViolation("EMPTY_CALIBRATION_OUTCOME_SET")
    if len(outcome_ids) != len(set(outcome_ids)):
        raise InvariantViolation("DUPLICATE_CALIBRATION_OUTCOME_ID")
    latest_outcomes: list[ExecutionOutcome] = []
    for outcome_id in sorted(outcome_ids):
        history = evidence_ledger.history(outcome_id)
        if not history:
            raise InvariantViolation(
                f"UNKNOWN_CALIBRATION_OUTCOME:{outcome_id}"
            )
        outcome = history[-1]
        if outcome.origin is not EvidenceOrigin.BROKER_OBSERVED:
            raise InvariantViolation(
                f"NON_OBSERVED_EVIDENCE_IN_CALIBRATION:{outcome_id}"
            )
        latest_outcomes.append(outcome)
    latest = tuple(
        sorted(
            latest_outcomes,
            key=lambda outcome: (
                outcome.context.sha256(),
                outcome.outcome_id,
                outcome.version,
            ),
        )
    )
    tolerance_values = tuple(tolerances)
    families = [value.family for value in tolerance_values]
    if len(families) != len(set(families)):
        raise InvariantViolation("DUPLICATE_REALITY_GAP_TOLERANCE")
    missing_families = set(_REALITY_GAP_ORDER) - set(families)
    if missing_families:
        raise InvariantViolation("MISSING_REALITY_GAP_TOLERANCE")
    if len(families) != len(_REALITY_GAP_ORDER):
        raise InvariantViolation("INVALID_REALITY_GAP_TOLERANCE_SET")
    tolerance_by_family = {
        value.family: value for value in tolerance_values
    }
    predictions_by_context = {
        prediction.context_key: prediction
        for prediction in prediction_surface.predictions
    }
    outcomes_by_context: dict[str, list[ExecutionOutcome]] = {}
    for outcome in latest:
        outcomes_by_context.setdefault(
            outcome.context.sha256(),
            [],
        ).append(outcome)
    predicted_keys = set(predictions_by_context)
    observed_keys = set(outcomes_by_context)
    missing_prediction = tuple(sorted(observed_keys - predicted_keys))
    missing_observed = tuple(sorted(predicted_keys - observed_keys))
    gaps: list[ContextRealityGap] = []
    for context_key in sorted(predicted_keys & observed_keys):
        prediction = predictions_by_context[context_key]
        context_outcomes = tuple(outcomes_by_context[context_key])
        for family in _REALITY_GAP_ORDER:
            tolerance = tolerance_by_family[family]
            predicted = _predicted_distribution(prediction, family)
            values = _observed_values(context_outcomes, family)
            observed = _observed_distribution(
                _REALITY_GAP_KIND[family],
                values,
            )
            reasons: list[str] = []
            p50_gap: Decimal | None = None
            p95_gap: Decimal | None = None
            if len(values) < tolerance.min_observations:
                status = GapStatus.INSUFFICIENT_OBSERVATIONS
                reasons.append("INSUFFICIENT_OBSERVATIONS")
            else:
                if observed is None:
                    raise InvariantViolation(
                        "OBSERVED_DISTRIBUTION_MISSING_AFTER_MINIMUM"
                    )
                p50_gap = abs(predicted.p50 - observed.p50)
                p95_gap = abs(predicted.p95 - observed.p95)
                if p50_gap > tolerance.max_p50_absolute_gap:
                    reasons.append("P50_GAP_EXCEEDED")
                if p95_gap > tolerance.max_p95_absolute_gap:
                    reasons.append("P95_GAP_EXCEEDED")
                status = GapStatus.FAIL if reasons else GapStatus.PASS
            gaps.append(
                ContextRealityGap(
                    context=prediction.context,
                    family=family,
                    predicted_distribution=predicted,
                    observed_distribution=observed,
                    p50_absolute_gap=p50_gap,
                    p95_absolute_gap=p95_gap,
                    tolerance_sha256=tolerance.sha256(),
                    observation_count=len(values),
                    status=status,
                    reasons=tuple(reasons),
                )
            )
    ordered_tolerances = tuple(
        tolerance_by_family[family].sha256()
        for family in _REALITY_GAP_ORDER
    )
    outcome_sha256s = tuple(
        sorted(outcome.sha256() for outcome in latest)
    )
    all_passed = (
        bool(gaps)
        and not missing_prediction
        and not missing_observed
        and all(gap.status is GapStatus.PASS for gap in gaps)
    )
    return CalibrationReport(
        report_id=report_id,
        version=version,
        model_id=model_definition.model_id,
        model_version=model_definition.version,
        model_definition_sha256=model_sha,
        prediction_surface_sha256=prediction_surface.sha256(),
        observed_outcome_sha256s=outcome_sha256s,
        observed_evidence_root_sha256=canonical_sha256(outcome_sha256s),
        tolerance_sha256s=ordered_tolerances,
        context_gaps=tuple(gaps),
        missing_prediction_context_keys=missing_prediction,
        missing_observed_context_keys=missing_observed,
        created_at_ns=created_at_ns,
        all_required_gaps_passed=all_passed,
    )


@dataclass(frozen=True, slots=True)
class CalibrationReview:
    review_id: str
    reviewer_id: str
    reviewer_role: DatasetRole
    report_sha256: str
    approved: bool
    human_approval_id: str | None
    minority_findings: tuple[str, ...]
    unresolved_findings: tuple[str, ...]
    reviewed_at_ns: int
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "review_id",
            _identifier(self.review_id, "INVALID_CALIBRATION_REVIEW_ID"),
        )
        object.__setattr__(
            self,
            "reviewer_id",
            _identifier(self.reviewer_id, "INVALID_CALIBRATION_REVIEWER_ID"),
        )
        if not isinstance(self.reviewer_role, DatasetRole):
            raise InvariantViolation("INVALID_CALIBRATION_REVIEWER_ROLE")
        _digest(self.report_sha256, "INVALID_CALIBRATION_REPORT_SHA256")
        if not isinstance(self.approved, bool):
            raise InvariantViolation("INVALID_CALIBRATION_REVIEW_APPROVAL")
        if self.human_approval_id is not None:
            object.__setattr__(
                self,
                "human_approval_id",
                _identifier(
                    self.human_approval_id,
                    "INVALID_CALIBRATION_HUMAN_APPROVAL_ID",
                ),
            )
        minority = tuple(
            _text(value, "INVALID_CALIBRATION_MINORITY_FINDING")
            for value in self.minority_findings
        )
        unresolved = tuple(
            _text(value, "INVALID_CALIBRATION_UNRESOLVED_FINDING")
            for value in self.unresolved_findings
        )
        if len(minority) != len(set(minority)):
            raise InvariantViolation("DUPLICATE_CALIBRATION_MINORITY_FINDING")
        if len(unresolved) != len(set(unresolved)):
            raise InvariantViolation("DUPLICATE_CALIBRATION_UNRESOLVED_FINDING")
        object.__setattr__(self, "minority_findings", minority)
        object.__setattr__(self, "unresolved_findings", unresolved)
        _nonnegative_int(self.reviewed_at_ns, "INVALID_CALIBRATION_REVIEW_TIME")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("CALIBRATION_REVIEW_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_role": self.reviewer_role,
            "report_sha256": self.report_sha256,
            "approved": self.approved,
            "human_approval_id": self.human_approval_id,
            "minority_findings": self.minority_findings,
            "unresolved_findings": self.unresolved_findings,
            "reviewed_at_ns": self.reviewed_at_ns,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class CalibrationRequest:
    request_id: str
    challenger_model_id: str
    challenger_model_version: int
    model_definition_sha256: str
    report_sha256: str
    requested_by_id: str
    requested_by_role: DatasetRole
    independent_review: CalibrationReview
    rollback_plan: str | None
    requested_at_ns: int
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_id",
            _identifier(self.request_id, "INVALID_CALIBRATION_REQUEST_ID"),
        )
        object.__setattr__(
            self,
            "challenger_model_id",
            _identifier(
                self.challenger_model_id,
                "INVALID_CHALLENGER_MODEL_ID",
            ),
        )
        _positive_int(
            self.challenger_model_version,
            "INVALID_FILL_MODEL_VERSION",
        )
        _digest(
            self.model_definition_sha256,
            "INVALID_MODEL_DEFINITION_SHA256",
        )
        _digest(self.report_sha256, "INVALID_CALIBRATION_REPORT_SHA256")
        object.__setattr__(
            self,
            "requested_by_id",
            _identifier(
                self.requested_by_id,
                "INVALID_CALIBRATION_REQUESTER_ID",
            ),
        )
        if not isinstance(self.requested_by_role, DatasetRole):
            raise InvariantViolation("INVALID_CALIBRATION_REQUESTER_ROLE")
        if not isinstance(self.independent_review, CalibrationReview):
            raise InvariantViolation("CALIBRATION_REVIEW_REQUIRED")
        if self.rollback_plan is not None:
            object.__setattr__(
                self,
                "rollback_plan",
                _text(
                    self.rollback_plan,
                    "INVALID_CALIBRATION_ROLLBACK_PLAN",
                ),
            )
        _nonnegative_int(self.requested_at_ns, "INVALID_CALIBRATION_REQUEST_TIME")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("CALIBRATION_REQUEST_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "challenger_model_id": self.challenger_model_id,
            "challenger_model_version": self.challenger_model_version,
            "model_definition_sha256": self.model_definition_sha256,
            "report_sha256": self.report_sha256,
            "requested_by_id": self.requested_by_id,
            "requested_by_role": self.requested_by_role,
            "independent_review": self.independent_review,
            "rollback_plan": self.rollback_plan,
            "requested_at_ns": self.requested_at_ns,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class CalibrationDecisionState(str, Enum):
    BLOCKED = "BLOCKED"
    ELIGIBLE_AS_CHALLENGER = "ELIGIBLE_AS_CHALLENGER"


@dataclass(frozen=True, slots=True)
class CalibrationDecision:
    state: CalibrationDecisionState
    request_id: str
    challenger_model_id: str
    reasons: tuple[str, ...]
    request_sha256: str
    report_sha256: str
    model_definition_sha256: str
    review_sha256: str
    decision_sha256: str
    production_calibrated: bool = False
    execution_simulator_calibrated: bool = False
    challenger_selected: bool = False
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        if not isinstance(self.state, CalibrationDecisionState):
            raise InvariantViolation("INVALID_CALIBRATION_DECISION_STATE")
        reasons = tuple(self.reasons)
        if len(reasons) != len(set(reasons)):
            raise InvariantViolation("DUPLICATE_CALIBRATION_DECISION_REASON")
        object.__setattr__(self, "reasons", reasons)
        if self.state is CalibrationDecisionState.BLOCKED and not reasons:
            raise InvariantViolation("BLOCKED_CALIBRATION_REQUIRES_REASON")
        if (
            self.state is CalibrationDecisionState.ELIGIBLE_AS_CHALLENGER
            and reasons
        ):
            raise InvariantViolation("ELIGIBLE_CHALLENGER_HAS_REASONS")
        for value, code in (
            (self.request_sha256, "INVALID_CALIBRATION_REQUEST_SHA256"),
            (self.report_sha256, "INVALID_CALIBRATION_REPORT_SHA256"),
            (
                self.model_definition_sha256,
                "INVALID_MODEL_DEFINITION_SHA256",
            ),
            (self.review_sha256, "INVALID_CALIBRATION_REVIEW_SHA256"),
            (self.decision_sha256, "INVALID_CALIBRATION_DECISION_SHA256"),
        ):
            _digest(value, code)
        if self.production_calibrated is not False:
            raise InvariantViolation(
                "PRODUCTION_EXECUTION_CALIBRATION_FORBIDDEN"
            )
        if self.execution_simulator_calibrated is not False:
            raise InvariantViolation(
                "EXECUTION_SIMULATOR_CALIBRATION_FORBIDDEN"
            )
        if self.challenger_selected is not False:
            raise InvariantViolation("CHALLENGER_SELECTION_FORBIDDEN")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("CALIBRATION_DECISION_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("CALIBRATION_DECISION_CANNOT_PROVE_PROFITABILITY")
        if self.decision_sha256 != self.recomputed_sha256():
            raise InvariantViolation("CALIBRATION_DECISION_SHA256_MISMATCH")

    def canonical_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "state": self.state,
            "request_id": self.request_id,
            "challenger_model_id": self.challenger_model_id,
            "reasons": self.reasons,
            "request_sha256": self.request_sha256,
            "report_sha256": self.report_sha256,
            "model_definition_sha256": self.model_definition_sha256,
            "review_sha256": self.review_sha256,
            "production_calibrated": self.production_calibrated,
            "execution_simulator_calibrated": (
                self.execution_simulator_calibrated
            ),
            "challenger_selected": self.challenger_selected,
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }
        if include_hash:
            value["decision_sha256"] = self.decision_sha256
        return value

    def recomputed_sha256(self) -> str:
        return canonical_sha256(self.canonical_dict(include_hash=False))


class CalibrationGate:
    live_trading_state = "HARD_LOCKED"
    production_calibrated = False
    execution_simulator_calibrated = False
    challenger_selected = False

    @staticmethod
    def _reason(reasons: list[str], value: str) -> None:
        if value not in reasons:
            reasons.append(value)

    def evaluate(
        self,
        request: CalibrationRequest,
        report: CalibrationReport,
        model_definition: FillModelDefinition,
    ) -> CalibrationDecision:
        reasons: list[str] = []
        try:
            report.assert_integrity()
        except InvariantViolation as exc:
            self._reason(reasons, str(exc).split(":", 1)[0])
        report_sha = report.sha256()
        model_sha = model_definition.sha256()
        review = request.independent_review
        if request.report_sha256 != report_sha:
            self._reason(reasons, "CALIBRATION_REPORT_MISMATCH")
        if review.report_sha256 != report_sha:
            self._reason(reasons, "CALIBRATION_REVIEW_REPORT_MISMATCH")
        if request.model_definition_sha256 != model_sha:
            self._reason(reasons, "CALIBRATION_MODEL_DEFINITION_MISMATCH")
        if (
            request.challenger_model_id != model_definition.model_id
            or request.challenger_model_version != model_definition.version
        ):
            self._reason(reasons, "CALIBRATION_MODEL_IDENTITY_MISMATCH")
        if (
            report.model_definition_sha256 != model_sha
            or report.model_id != model_definition.model_id
            or report.model_version != model_definition.version
        ):
            self._reason(reasons, "CALIBRATION_REPORT_MODEL_MISMATCH")
        if model_definition.challenger_of_model_id is None:
            self._reason(reasons, "CHALLENGER_MODEL_REQUIRED")
        if not report.all_required_gaps_passed:
            self._reason(reasons, "REALITY_GAP_FAILURE")
        if report.missing_prediction_context_keys:
            self._reason(reasons, "MISSING_PREDICTION_CONTEXT")
        if report.missing_observed_context_keys:
            self._reason(reasons, "MISSING_OBSERVED_CONTEXT")
        if review.reviewer_role is not DatasetRole.INDEPENDENT_EVALUATOR:
            self._reason(
                reasons,
                "INDEPENDENT_CALIBRATION_REVIEW_REQUIRED",
            )
        if review.reviewer_id == request.requested_by_id:
            self._reason(reasons, "CALIBRATION_SELF_REVIEW_FORBIDDEN")
        if not review.approved:
            self._reason(reasons, "CALIBRATION_REVIEW_APPROVAL_REQUIRED")
        if review.human_approval_id is None:
            self._reason(reasons, "CALIBRATION_HUMAN_APPROVAL_REQUIRED")
        if not review.minority_findings:
            self._reason(reasons, "CALIBRATION_MINORITY_FINDINGS_REQUIRED")
        if review.unresolved_findings:
            self._reason(reasons, "CALIBRATION_UNRESOLVED_FINDINGS")
        if request.rollback_plan is None:
            self._reason(reasons, "CALIBRATION_ROLLBACK_PLAN_REQUIRED")
        if review.reviewed_at_ns < report.created_at_ns:
            self._reason(reasons, "CALIBRATION_REVIEW_BEFORE_REPORT")
        if request.requested_at_ns < review.reviewed_at_ns:
            self._reason(reasons, "CALIBRATION_REQUEST_BEFORE_REVIEW")
        state = (
            CalibrationDecisionState.BLOCKED
            if reasons
            else CalibrationDecisionState.ELIGIBLE_AS_CHALLENGER
        )
        payload = {
            "state": state,
            "request_id": request.request_id,
            "challenger_model_id": request.challenger_model_id,
            "reasons": tuple(reasons),
            "request_sha256": request.sha256(),
            "report_sha256": report_sha,
            "model_definition_sha256": model_sha,
            "review_sha256": review.sha256(),
            "production_calibrated": False,
            "execution_simulator_calibrated": False,
            "challenger_selected": False,
            "live_trading_state": "HARD_LOCKED",
            "profitability_state": "UNPROVEN",
        }
        return CalibrationDecision(
            state=state,
            request_id=request.request_id,
            challenger_model_id=request.challenger_model_id,
            reasons=tuple(reasons),
            request_sha256=request.sha256(),
            report_sha256=report_sha,
            model_definition_sha256=model_sha,
            review_sha256=review.sha256(),
            decision_sha256=canonical_sha256(payload),
        )
