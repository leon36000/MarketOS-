"""Deterministic, fail-closed paper-mode Risk Kernel."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .money import Money, Price, Quantity, RoundingPolicy
from .orders import ExecutionMode, OrderIntent, OrderSide
from .time import ClockQuality


class RiskAction(str, Enum):
    ALLOW = "ALLOW"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    currency: str
    allowed_instruments: frozenset[str]
    max_order_notional: Money
    max_gross_notional: Money
    max_position_quantity: Quantity
    max_data_age_ns: int
    max_clock_sync_age_ns: int
    max_clock_error_ns: int
    allow_short: bool = False

    def __post_init__(self) -> None:
        currency = self.currency.upper()
        object.__setattr__(self, "currency", currency)
        if not self.allowed_instruments:
            raise InvariantViolation("EMPTY_INSTRUMENT_ALLOWLIST")
        if self.max_order_notional.currency != currency or self.max_gross_notional.currency != currency:
            raise InvariantViolation("RISK_LIMIT_CURRENCY_MISMATCH")
        if self.max_order_notional.minor_units <= 0 or self.max_gross_notional.minor_units <= 0:
            raise InvariantViolation("INVALID_NOTIONAL_LIMIT")
        if self.max_position_quantity.value <= 0:
            raise InvariantViolation("INVALID_POSITION_LIMIT")
        for value in (self.max_data_age_ns, self.max_clock_sync_age_ns, self.max_clock_error_ns):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvariantViolation("INVALID_TIME_RISK_LIMIT")
        object.__setattr__(self, "allowed_instruments", frozenset(self.allowed_instruments))

    def canonical_dict(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "allowed_instruments": self.allowed_instruments,
            "max_order_notional": self.max_order_notional,
            "max_gross_notional": self.max_gross_notional,
            "max_position_quantity": self.max_position_quantity,
            "max_data_age_ns": self.max_data_age_ns,
            "max_clock_sync_age_ns": self.max_clock_sync_age_ns,
            "max_clock_error_ns": self.max_clock_error_ns,
            "allow_short": self.allow_short,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class RiskContext:
    now_ns: int
    data_available_at_ns: int
    books_reconciled: bool
    clock_quality: ClockQuality
    cash: Money
    current_position: Quantity
    current_gross_notional: Money
    mark_price: Price
    estimated_fee: Money

    def __post_init__(self) -> None:
        for value in (self.now_ns, self.data_available_at_ns):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvariantViolation("INVALID_RISK_CONTEXT_TIME")
        if self.estimated_fee.minor_units < 0:
            raise InvariantViolation("NEGATIVE_FEE")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "now_ns": self.now_ns,
            "data_available_at_ns": self.data_available_at_ns,
            "books_reconciled": self.books_reconciled,
            "clock_quality": self.clock_quality,
            "cash": self.cash,
            "current_position": self.current_position,
            "current_gross_notional": self.current_gross_notional,
            "mark_price": self.mark_price,
            "estimated_fee": self.estimated_fee,
        }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    action: RiskAction
    intent_id: str
    approved_quantity: Quantity | None
    reasons: tuple[str, ...]
    limits_sha256: str
    intent_sha256: str
    context_sha256: str
    decision_sha256: str
    live_trading_state: str = "HARD_LOCKED"

    def canonical_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "intent_id": self.intent_id,
            "approved_quantity": self.approved_quantity,
            "reasons": self.reasons,
            "limits_sha256": self.limits_sha256,
            "intent_sha256": self.intent_sha256,
            "context_sha256": self.context_sha256,
            "decision_sha256": self.decision_sha256,
            "live_trading_state": self.live_trading_state,
        }


class RiskKernel:
    LIVE_TRADING_STATE = "HARD_LOCKED"

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        reasons: list[str] = []
        limits = self.limits
        currency = limits.currency
        for money in (context.cash, context.current_gross_notional, context.estimated_fee):
            if money.currency != currency:
                reasons.append("RISK_CONTEXT_CURRENCY_MISMATCH")
        if context.mark_price.currency != currency:
            reasons.append("MARK_PRICE_CURRENCY_MISMATCH")
        if intent.limit_price is not None and intent.limit_price.currency != currency:
            reasons.append("LIMIT_PRICE_CURRENCY_MISMATCH")
        if intent.mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW}:
            reasons.append("EXECUTION_MODE_NOT_ALLOWED")
        if context.now_ns < intent.valid_from_ns:
            reasons.append("INTENT_NOT_YET_VALID")
        if context.now_ns > intent.expires_at_ns:
            reasons.append("INTENT_EXPIRED")
        if context.data_available_at_ns > context.now_ns:
            reasons.append("FUTURE_DATA")
        elif context.now_ns - context.data_available_at_ns > limits.max_data_age_ns:
            reasons.append("STALE_DATA")
        if not context.books_reconciled:
            reasons.append("BOOKS_UNRECONCILED")
        if not context.clock_quality.is_acceptable(
            now_wall_ns=context.now_ns,
            max_age_ns=limits.max_clock_sync_age_ns,
            max_error_ns=limits.max_clock_error_ns,
        ):
            reasons.append("CLOCK_QUALITY_UNACCEPTABLE")
        if intent.instrument_id not in limits.allowed_instruments:
            reasons.append("INSTRUMENT_NOT_ALLOWED")

        notional = context.mark_price.notional(intent.quantity, rounding=RoundingPolicy.HALF_EVEN)
        if notional.minor_units > limits.max_order_notional.minor_units:
            reasons.append("ORDER_NOTIONAL_LIMIT")
        if (
            context.current_gross_notional.currency == currency
            and context.current_gross_notional.minor_units + notional.minor_units
            > limits.max_gross_notional.minor_units
        ):
            reasons.append("GROSS_NOTIONAL_LIMIT")

        if intent.side is OrderSide.BUY:
            if context.cash.currency == currency and context.cash.minor_units < (
                notional.minor_units + context.estimated_fee.minor_units
            ):
                reasons.append("INSUFFICIENT_CASH")
            resulting_quantity = context.current_position.value + intent.quantity.value
            if resulting_quantity > limits.max_position_quantity.value:
                reasons.append("POSITION_QUANTITY_LIMIT")
        else:
            if not limits.allow_short and context.current_position.value < intent.quantity.value:
                reasons.append("INSUFFICIENT_POSITION")

        action = RiskAction.NO_TRADE if reasons else RiskAction.ALLOW
        approved = intent.quantity if action is RiskAction.ALLOW else None
        reasons_tuple = tuple(reasons)
        payload = {
            "action": action,
            "intent_id": intent.intent_id,
            "approved_quantity": approved,
            "reasons": reasons_tuple,
            "limits_sha256": limits.sha256(),
            "intent_sha256": intent.sha256(),
            "context_sha256": canonical_sha256(context.canonical_dict()),
            "live_trading_state": self.LIVE_TRADING_STATE,
        }
        decision_sha256 = canonical_sha256(payload)
        return RiskDecision(
            action=action,
            intent_id=intent.intent_id,
            approved_quantity=approved,
            reasons=reasons_tuple,
            limits_sha256=payload["limits_sha256"],
            intent_sha256=payload["intent_sha256"],
            context_sha256=payload["context_sha256"],
            decision_sha256=decision_sha256,
            live_trading_state=self.LIVE_TRADING_STATE,
        )
