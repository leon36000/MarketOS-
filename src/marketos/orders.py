"""Immutable non-live order intent contracts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .money import Price, Quantity

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ExecutionMode(str, Enum):
    SHADOW = "SHADOW"
    PAPER = "PAPER"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    IOC = "IOC"
    DAY = "DAY"
    GTC = "GTC"


class OrderState(str, Enum):
    PROPOSED = "PROPOSED"
    RISK_APPROVED = "RISK_APPROVED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    intent_id: str
    client_order_id: str
    idempotency_key: str
    instrument_id: str
    side: OrderSide
    quantity: Quantity
    order_type: OrderType
    limit_price: Price | None
    time_in_force: TimeInForce
    created_at_ns: int
    valid_from_ns: int
    expires_at_ns: int
    strategy_version: str
    config_sha256: str
    mode: ExecutionMode

    def __post_init__(self) -> None:
        for value, code in (
            (self.intent_id, "MISSING_INTENT_ID"),
            (self.client_order_id, "MISSING_CLIENT_ORDER_ID"),
            (self.idempotency_key, "MISSING_IDEMPOTENCY_KEY"),
            (self.instrument_id, "MISSING_INSTRUMENT_ID"),
            (self.strategy_version, "MISSING_STRATEGY_VERSION"),
        ):
            if not value.strip():
                raise InvariantViolation(code)
        if self.quantity.value <= 0:
            raise InvariantViolation("POSITIVE_QUANTITY_REQUIRED")
        if not isinstance(self.side, OrderSide):
            raise InvariantViolation("INVALID_ORDER_SIDE")
        if not isinstance(self.order_type, OrderType):
            raise InvariantViolation("INVALID_ORDER_TYPE")
        if not isinstance(self.time_in_force, TimeInForce):
            raise InvariantViolation("INVALID_TIME_IN_FORCE")
        if not isinstance(self.mode, ExecutionMode):
            raise InvariantViolation("INVALID_EXECUTION_MODE")
        for value in (self.created_at_ns, self.valid_from_ns, self.expires_at_ns):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvariantViolation("INVALID_INTENT_TIME")
        if not self.created_at_ns <= self.valid_from_ns <= self.expires_at_ns:
            raise InvariantViolation("INVALID_INTENT_TIME_ORDER")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise InvariantViolation("MARKET_ORDER_CANNOT_HAVE_LIMIT")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise InvariantViolation("LIMIT_ORDER_REQUIRES_PRICE")
        if not _HEX64.fullmatch(self.config_sha256):
            raise InvariantViolation("INVALID_CONFIG_SHA256")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "idempotency_key": self.idempotency_key,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force,
            "created_at_ns": self.created_at_ns,
            "valid_from_ns": self.valid_from_ns,
            "expires_at_ns": self.expires_at_ns,
            "strategy_version": self.strategy_version,
            "config_sha256": self.config_sha256,
            "mode": self.mode,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def as_kwargs(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "idempotency_key": self.idempotency_key,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force,
            "created_at_ns": self.created_at_ns,
            "valid_from_ns": self.valid_from_ns,
            "expires_at_ns": self.expires_at_ns,
            "strategy_version": self.strategy_version,
            "config_sha256": self.config_sha256,
            "mode": self.mode,
        }
