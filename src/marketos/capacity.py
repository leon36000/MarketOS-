"""Conservative research-only capacity bounds.

Capacity is computed from a lower-confidence gross edge, upper-confidence
impact/cost/uncertainty and the minimum complete operational constraint set.
The result never authorizes capital, selects a strategy or proves edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .money import Money

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


def _decimal(value: Decimal, code: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(code)
    return value


def _digest(value: str, code: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise InvariantViolation(code)
    return value


class CapacityDistributionKind(str, Enum):
    GROSS_EDGE_BPS = "GROSS_EDGE_BPS"
    IMPACT_BPS = "IMPACT_BPS"
    OPERATING_COST_BPS = "OPERATING_COST_BPS"
    UNCERTAINTY_BPS = "UNCERTAINTY_BPS"


_NONNEGATIVE_KINDS = {
    CapacityDistributionKind.IMPACT_BPS,
    CapacityDistributionKind.OPERATING_COST_BPS,
    CapacityDistributionKind.UNCERTAINTY_BPS,
}


@dataclass(frozen=True, slots=True)
class CapacityDistribution:
    kind: CapacityDistributionKind
    p05: Decimal
    p50: Decimal
    p95: Decimal
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CapacityDistributionKind):
            raise InvariantViolation("INVALID_CAPACITY_DISTRIBUTION_KIND")
        p05 = _decimal(self.p05, "INVALID_CAPACITY_DISTRIBUTION")
        p50 = _decimal(self.p50, "INVALID_CAPACITY_DISTRIBUTION")
        p95 = _decimal(self.p95, "INVALID_CAPACITY_DISTRIBUTION")
        if not p05 <= p50 <= p95:
            raise InvariantViolation("INVALID_CAPACITY_QUANTILES")
        if self.kind in _NONNEGATIVE_KINDS and p05 < 0:
            raise InvariantViolation("NEGATIVE_CAPACITY_COST_DISTRIBUTION")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 2
        ):
            raise InvariantViolation(
                "INSUFFICIENT_CAPACITY_DISTRIBUTION_SAMPLES"
            )
        object.__setattr__(self, "p05", p05)
        object.__setattr__(self, "p50", p50)
        object.__setattr__(self, "p95", p95)

    @property
    def unit(self) -> str:
        return "BPS"

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


_CONSTRAINT_FIELDS = (
    ("liquidity_notional_limit", "LIQUIDITY_NOTIONAL_LIMIT"),
    ("concentration_notional_limit", "CONCENTRATION_NOTIONAL_LIMIT"),
    ("turnover_notional_limit", "TURNOVER_NOTIONAL_LIMIT"),
    ("crowding_notional_limit", "CROWDING_NOTIONAL_LIMIT"),
    (
        "portfolio_interaction_notional_limit",
        "PORTFOLIO_INTERACTION_NOTIONAL_LIMIT",
    ),
)


@dataclass(frozen=True, slots=True)
class CapacityInputs:
    capacity_id: str
    version: int
    strategy_id: str
    strategy_version: int
    currency: str
    gross_edge_bps: CapacityDistribution
    impact_bps: CapacityDistribution
    operating_cost_bps: CapacityDistribution
    uncertainty_bps: CapacityDistribution
    liquidity_notional_limit: Money | None
    concentration_notional_limit: Money | None
    turnover_notional_limit: Money | None
    crowding_notional_limit: Money | None
    portfolio_interaction_notional_limit: Money | None
    borrow_required: bool
    borrow_available: bool
    borrow_notional_limit: Money | None
    calibration_report_sha256: str
    validation_evidence_sha256: str
    shadow_evidence_root_sha256: str
    created_at_ns: int
    capital_authorized: bool = False
    capacity_qualified: bool = False
    strategy_edge_proven: bool = False
    execution_simulator_calibrated: bool = False
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capacity_id",
            _identifier(self.capacity_id, "INVALID_CAPACITY_ID"),
        )
        _positive_int(self.version, "INVALID_CAPACITY_VERSION")
        object.__setattr__(
            self,
            "strategy_id",
            _identifier(self.strategy_id, "INVALID_CAPACITY_STRATEGY_ID"),
        )
        _positive_int(self.strategy_version, "INVALID_STRATEGY_VERSION")
        currency = Money.zero(self.currency).currency
        object.__setattr__(self, "currency", currency)
        expected = (
            (self.gross_edge_bps, CapacityDistributionKind.GROSS_EDGE_BPS),
            (self.impact_bps, CapacityDistributionKind.IMPACT_BPS),
            (
                self.operating_cost_bps,
                CapacityDistributionKind.OPERATING_COST_BPS,
            ),
            (self.uncertainty_bps, CapacityDistributionKind.UNCERTAINTY_BPS),
        )
        for distribution, kind in expected:
            if (
                not isinstance(distribution, CapacityDistribution)
                or distribution.kind is not kind
            ):
                raise InvariantViolation(
                    "CAPACITY_DISTRIBUTION_KIND_MISMATCH"
                )
        for field_name, _constraint_name in _CONSTRAINT_FIELDS:
            amount = getattr(self, field_name)
            if amount is None:
                continue
            if not isinstance(amount, Money) or amount.currency != currency:
                raise InvariantViolation("CAPACITY_CURRENCY_MISMATCH")
            if amount.minor_units <= 0:
                raise InvariantViolation("NON_POSITIVE_CAPACITY_CONSTRAINT")
        if not isinstance(self.borrow_required, bool) or not isinstance(
            self.borrow_available,
            bool,
        ):
            raise InvariantViolation("INVALID_BORROW_AVAILABILITY")
        if not self.borrow_required and (
            self.borrow_available or self.borrow_notional_limit is not None
        ):
            raise InvariantViolation("UNNEEDED_BORROW_LIMIT_FORBIDDEN")
        if self.borrow_notional_limit is not None:
            if (
                not isinstance(self.borrow_notional_limit, Money)
                or self.borrow_notional_limit.currency != currency
            ):
                raise InvariantViolation("CAPACITY_CURRENCY_MISMATCH")
            if self.borrow_notional_limit.minor_units <= 0:
                raise InvariantViolation("NON_POSITIVE_CAPACITY_CONSTRAINT")
        _digest(
            self.calibration_report_sha256,
            "INVALID_CALIBRATION_REPORT_SHA256",
        )
        _digest(
            self.validation_evidence_sha256,
            "INVALID_VALIDATION_EVIDENCE_SHA256",
        )
        _digest(
            self.shadow_evidence_root_sha256,
            "INVALID_SHADOW_EVIDENCE_ROOT_SHA256",
        )
        _nonnegative_int(self.created_at_ns, "INVALID_CAPACITY_CREATED_TIME")
        if self.capital_authorized is not False:
            raise InvariantViolation("CAPACITY_CANNOT_AUTHORIZE_CAPITAL")
        if self.capacity_qualified is not False:
            raise InvariantViolation("CAPACITY_QUALIFICATION_FORBIDDEN")
        if self.strategy_edge_proven is not False:
            raise InvariantViolation("CAPACITY_CANNOT_PROVE_EDGE")
        if self.execution_simulator_calibrated is not False:
            raise InvariantViolation(
                "CAPACITY_CANNOT_CLAIM_CALIBRATED_SIMULATOR"
            )
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("CAPACITY_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("CAPACITY_CANNOT_PROVE_PROFITABILITY")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "capacity_id": self.capacity_id,
            "version": self.version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "currency": self.currency,
            "gross_edge_bps": self.gross_edge_bps,
            "impact_bps": self.impact_bps,
            "operating_cost_bps": self.operating_cost_bps,
            "uncertainty_bps": self.uncertainty_bps,
            "liquidity_notional_limit": self.liquidity_notional_limit,
            "concentration_notional_limit": self.concentration_notional_limit,
            "turnover_notional_limit": self.turnover_notional_limit,
            "crowding_notional_limit": self.crowding_notional_limit,
            "portfolio_interaction_notional_limit": (
                self.portfolio_interaction_notional_limit
            ),
            "borrow_required": self.borrow_required,
            "borrow_available": self.borrow_available,
            "borrow_notional_limit": self.borrow_notional_limit,
            "calibration_report_sha256": self.calibration_report_sha256,
            "validation_evidence_sha256": self.validation_evidence_sha256,
            "shadow_evidence_root_sha256": self.shadow_evidence_root_sha256,
            "created_at_ns": self.created_at_ns,
            "capital_authorized": self.capital_authorized,
            "capacity_qualified": self.capacity_qualified,
            "strategy_edge_proven": self.strategy_edge_proven,
            "execution_simulator_calibrated": (
                self.execution_simulator_calibrated
            ),
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ResearchCapacityBound:
    capacity_id: str
    capacity_version: int
    input_sha256: str
    lower_confidence_net_edge_bps: Decimal
    research_notional_bound: Money
    binding_constraint: str | None
    constraint_values: tuple[tuple[str, Money], ...]
    zero_reasons: tuple[str, ...]
    calibration_report_sha256: str
    validation_evidence_sha256: str
    shadow_evidence_root_sha256: str
    capital_authorized: bool = False
    capacity_qualified: bool = False
    strategy_edge_proven: bool = False
    execution_simulator_calibrated: bool = False
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        _identifier(self.capacity_id, "INVALID_CAPACITY_ID")
        _positive_int(self.capacity_version, "INVALID_CAPACITY_VERSION")
        _digest(self.input_sha256, "INVALID_CAPACITY_INPUT_SHA256")
        edge = _decimal(
            self.lower_confidence_net_edge_bps,
            "INVALID_LOWER_CONFIDENCE_NET_EDGE",
        )
        object.__setattr__(self, "lower_confidence_net_edge_bps", edge)
        if not isinstance(self.research_notional_bound, Money):
            raise InvariantViolation("INVALID_RESEARCH_CAPACITY_BOUND")
        constraints = tuple(self.constraint_values)
        names = [name for name, _amount in constraints]
        if len(names) != len(set(names)):
            raise InvariantViolation("DUPLICATE_CAPACITY_CONSTRAINT")
        for name, amount in constraints:
            _text(name, "INVALID_CAPACITY_CONSTRAINT_NAME")
            if (
                not isinstance(amount, Money)
                or amount.currency != self.research_notional_bound.currency
                or amount.minor_units <= 0
            ):
                raise InvariantViolation("INVALID_CAPACITY_CONSTRAINT")
        object.__setattr__(self, "constraint_values", constraints)
        reasons = tuple(_text(reason, "INVALID_CAPACITY_ZERO_REASON") for reason in self.zero_reasons)
        if len(reasons) != len(set(reasons)):
            raise InvariantViolation("DUPLICATE_CAPACITY_ZERO_REASON")
        object.__setattr__(self, "zero_reasons", reasons)
        if reasons:
            if self.research_notional_bound.minor_units != 0:
                raise InvariantViolation("ZERO_CAPACITY_REASON_WITH_NONZERO_BOUND")
            if self.binding_constraint is not None:
                raise InvariantViolation("ZERO_CAPACITY_CANNOT_HAVE_BINDING_CONSTRAINT")
        else:
            if self.research_notional_bound.minor_units <= 0:
                raise InvariantViolation("POSITIVE_RESEARCH_CAPACITY_REQUIRED")
            if self.binding_constraint not in names:
                raise InvariantViolation("INVALID_BINDING_CAPACITY_CONSTRAINT")
        for value, code in (
            (
                self.calibration_report_sha256,
                "INVALID_CALIBRATION_REPORT_SHA256",
            ),
            (
                self.validation_evidence_sha256,
                "INVALID_VALIDATION_EVIDENCE_SHA256",
            ),
            (
                self.shadow_evidence_root_sha256,
                "INVALID_SHADOW_EVIDENCE_ROOT_SHA256",
            ),
        ):
            _digest(value, code)
        if self.capital_authorized is not False:
            raise InvariantViolation("CAPACITY_CANNOT_AUTHORIZE_CAPITAL")
        if self.capacity_qualified is not False:
            raise InvariantViolation("CAPACITY_QUALIFICATION_FORBIDDEN")
        if self.strategy_edge_proven is not False:
            raise InvariantViolation("CAPACITY_CANNOT_PROVE_EDGE")
        if self.execution_simulator_calibrated is not False:
            raise InvariantViolation(
                "CAPACITY_CANNOT_CLAIM_CALIBRATED_SIMULATOR"
            )
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("CAPACITY_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("CAPACITY_CANNOT_PROVE_PROFITABILITY")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "capacity_id": self.capacity_id,
            "capacity_version": self.capacity_version,
            "input_sha256": self.input_sha256,
            "lower_confidence_net_edge_bps": (
                self.lower_confidence_net_edge_bps
            ),
            "research_notional_bound": self.research_notional_bound,
            "binding_constraint": self.binding_constraint,
            "constraint_values": self.constraint_values,
            "zero_reasons": self.zero_reasons,
            "calibration_report_sha256": self.calibration_report_sha256,
            "validation_evidence_sha256": self.validation_evidence_sha256,
            "shadow_evidence_root_sha256": self.shadow_evidence_root_sha256,
            "capital_authorized": self.capital_authorized,
            "capacity_qualified": self.capacity_qualified,
            "strategy_edge_proven": self.strategy_edge_proven,
            "execution_simulator_calibrated": (
                self.execution_simulator_calibrated
            ),
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


def compute_research_capacity_bound(
    inputs: CapacityInputs,
) -> ResearchCapacityBound:
    if not isinstance(inputs, CapacityInputs):
        raise InvariantViolation("CAPACITY_INPUTS_REQUIRED")
    lower_edge = (
        inputs.gross_edge_bps.p05
        - inputs.impact_bps.p95
        - inputs.operating_cost_bps.p95
        - inputs.uncertainty_bps.p95
    )
    reasons: list[str] = []
    if lower_edge <= 0:
        reasons.append("NON_POSITIVE_LOWER_CONFIDENCE_EDGE")
    constraints: list[tuple[str, Money]] = []
    for field_name, constraint_name in _CONSTRAINT_FIELDS:
        amount = getattr(inputs, field_name)
        if amount is None:
            reasons.append(f"MISSING_{constraint_name}")
        else:
            constraints.append((constraint_name, amount))
    if inputs.borrow_required:
        if not inputs.borrow_available:
            reasons.append("BORROW_UNAVAILABLE")
        if inputs.borrow_notional_limit is None:
            reasons.append("MISSING_BORROW_NOTIONAL_LIMIT")
        else:
            constraints.append(
                ("BORROW_NOTIONAL_LIMIT", inputs.borrow_notional_limit)
            )
    zero_reasons = tuple(reasons)
    if zero_reasons:
        bound = Money.zero(inputs.currency)
        binding = None
    else:
        binding, bound = min(
            constraints,
            key=lambda item: (
                item[1].minor_units,
                next(
                    index
                    for index, value in enumerate(
                        tuple(name for _field, name in _CONSTRAINT_FIELDS)
                        + ("BORROW_NOTIONAL_LIMIT",)
                    )
                    if value == item[0]
                ),
            ),
        )
    return ResearchCapacityBound(
        capacity_id=inputs.capacity_id,
        capacity_version=inputs.version,
        input_sha256=inputs.sha256(),
        lower_confidence_net_edge_bps=lower_edge,
        research_notional_bound=bound,
        binding_constraint=binding,
        constraint_values=tuple(constraints),
        zero_reasons=zero_reasons,
        calibration_report_sha256=inputs.calibration_report_sha256,
        validation_evidence_sha256=inputs.validation_evidence_sha256,
        shadow_evidence_root_sha256=inputs.shadow_evidence_root_sha256,
    )
