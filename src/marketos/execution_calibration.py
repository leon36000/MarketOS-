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
from .execution_evidence import ExecutionContext

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
