"""Exact financial value types.

Cash is stored as integer minor units. Quantities and prices use Decimal values
constructed from text; binary floating point is rejected at the boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
from enum import Enum
import re
from typing import ClassVar

from .errors import InvariantViolation

_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _decimal(value: str | int | Decimal, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise InvariantViolation(f"INVALID_{field.upper()}")
    if isinstance(value, float):
        raise InvariantViolation("FLOAT_FORBIDDEN")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:  # Decimal raises several concrete exceptions
        raise InvariantViolation(f"INVALID_{field.upper()}") from exc
    if not result.is_finite():
        raise InvariantViolation(f"NON_FINITE_{field.upper()}")
    return result


class RoundingPolicy(str, Enum):
    REJECT = "REJECT"
    HALF_EVEN = "HALF_EVEN"
    HALF_UP = "HALF_UP"
    DOWN = "DOWN"

    def decimal_mode(self) -> str:
        return {
            RoundingPolicy.HALF_EVEN: ROUND_HALF_EVEN,
            RoundingPolicy.HALF_UP: ROUND_HALF_UP,
            RoundingPolicy.DOWN: ROUND_DOWN,
        }[self]


@dataclass(frozen=True, slots=True)
class CurrencySpec:
    code: str
    exponent: int

    _KNOWN: ClassVar[dict[str, int]] = {
        "USD": 2,
        "CAD": 2,
        "EUR": 2,
        "GBP": 2,
        "CHF": 2,
        "AUD": 2,
        "NZD": 2,
        "HKD": 2,
        "SGD": 2,
        "JPY": 0,
    }

    def __post_init__(self) -> None:
        if not _CURRENCY.fullmatch(self.code):
            raise InvariantViolation("INVALID_CURRENCY")
        if not 0 <= self.exponent <= 9:
            raise InvariantViolation("INVALID_CURRENCY_EXPONENT")

    @classmethod
    def for_code(cls, code: str) -> "CurrencySpec":
        normalized = code.upper()
        if normalized not in cls._KNOWN:
            raise InvariantViolation(f"UNKNOWN_CURRENCY:{normalized}")
        return cls(normalized, cls._KNOWN[normalized])

    @classmethod
    def register(cls, code: str, exponent: int) -> None:
        spec = cls(code.upper(), exponent)
        existing = cls._KNOWN.get(spec.code)
        if existing is not None and existing != exponent:
            raise InvariantViolation("CURRENCY_SPEC_CONFLICT")
        cls._KNOWN[spec.code] = exponent

    @property
    def scale(self) -> int:
        return 10**self.exponent


@dataclass(frozen=True, slots=True)
class Money:
    currency: str
    minor_units: int

    def __post_init__(self) -> None:
        spec = CurrencySpec.for_code(self.currency)
        object.__setattr__(self, "currency", spec.code)
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise InvariantViolation("MONEY_MINOR_UNITS_MUST_BE_INT")

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(currency.upper(), 0)

    @classmethod
    def from_decimal(
        cls,
        currency: str,
        value: str | int | Decimal,
        *,
        rounding: RoundingPolicy = RoundingPolicy.REJECT,
    ) -> "Money":
        spec = CurrencySpec.for_code(currency)
        decimal_value = _decimal(value, field="money")
        scaled = decimal_value * spec.scale
        integral = scaled.to_integral_value()
        if scaled != integral:
            if rounding is RoundingPolicy.REJECT:
                raise InvariantViolation("ROUNDING_REQUIRED")
            integral = scaled.to_integral_value(rounding=rounding.decimal_mode())
        return cls(spec.code, int(integral))

    def to_decimal(self) -> Decimal:
        spec = CurrencySpec.for_code(self.currency)
        quantum = Decimal(1).scaleb(-spec.exponent)
        return (Decimal(self.minor_units) / spec.scale).quantize(quantum)

    def _same(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise InvariantViolation("CURRENCY_MISMATCH")

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._same(other)
        return Money(self.currency, self.minor_units + other.minor_units)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._same(other)
        return Money(self.currency, self.minor_units - other.minor_units)

    def __neg__(self) -> "Money":
        return Money(self.currency, -self.minor_units)

    def __mul__(self, factor: int) -> "Money":
        if isinstance(factor, bool) or not isinstance(factor, int):
            return NotImplemented
        return Money(self.currency, self.minor_units * factor)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor_units < other.minor_units

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor_units <= other.minor_units

    def canonical_dict(self) -> dict[str, object]:
        return {"currency": self.currency, "minor_units": self.minor_units}


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        parsed = _decimal(self.value, field="quantity")
        if parsed < 0:
            raise InvariantViolation("NEGATIVE_QUANTITY")
        object.__setattr__(self, "value", parsed.normalize() if parsed else Decimal("0"))

    @classmethod
    def parse(cls, value: str | int | Decimal) -> "Quantity":
        return cls(_decimal(value, field="quantity"))

    @classmethod
    def positive(cls, value: str | int | Decimal) -> "Quantity":
        quantity = cls.parse(value)
        if quantity.value <= 0:
            raise InvariantViolation("POSITIVE_QUANTITY_REQUIRED")
        return quantity

    def __add__(self, other: "Quantity") -> "Quantity":
        if not isinstance(other, Quantity):
            return NotImplemented
        return Quantity(self.value + other.value)

    def __sub__(self, other: "Quantity") -> "Quantity":
        if not isinstance(other, Quantity):
            return NotImplemented
        result = self.value - other.value
        if result < 0:
            raise InvariantViolation("NEGATIVE_QUANTITY")
        return Quantity(result)

    def canonical_dict(self) -> dict[str, object]:
        return {"value": self.value}


@dataclass(frozen=True, slots=True)
class Price:
    currency: str
    value: Decimal
    tick_size: Decimal

    def __post_init__(self) -> None:
        spec = CurrencySpec.for_code(self.currency)
        price = _decimal(self.value, field="price")
        tick = _decimal(self.tick_size, field="tick_size")
        if price < 0:
            raise InvariantViolation("NEGATIVE_PRICE")
        if tick <= 0:
            raise InvariantViolation("INVALID_TICK_SIZE")
        if price % tick != 0:
            raise InvariantViolation("PRICE_NOT_TICK_ALIGNED")
        object.__setattr__(self, "currency", spec.code)
        object.__setattr__(self, "value", price.normalize() if price else Decimal("0"))
        object.__setattr__(self, "tick_size", tick.normalize())

    @classmethod
    def parse(
        cls,
        currency: str,
        value: str | int | Decimal,
        *,
        tick_size: str | int | Decimal,
    ) -> "Price":
        return cls(currency.upper(), _decimal(value, field="price"), _decimal(tick_size, field="tick_size"))

    def notional(
        self,
        quantity: Quantity,
        *,
        rounding: RoundingPolicy = RoundingPolicy.REJECT,
    ) -> Money:
        if not isinstance(quantity, Quantity):
            raise InvariantViolation("INVALID_QUANTITY")
        return Money.from_decimal(self.currency, self.value * quantity.value, rounding=rounding)

    def canonical_dict(self) -> dict[str, object]:
        return {"currency": self.currency, "value": self.value, "tick_size": self.tick_size}
