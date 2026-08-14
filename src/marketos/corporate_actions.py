"""Append-only corporate actions and separate adjustment-factor views."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from .canonical import canonical_sha256
from .errors import DuplicateConflict, InvariantViolation
from .money import Price

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ActionFamily(str, Enum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    SPIN_OFF = "SPIN_OFF"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    TENDER_OFFER = "TENDER_OFFER"
    REDEMPTION = "REDEMPTION"
    NAME_CHANGE = "NAME_CHANGE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    NEW_LISTING = "NEW_LISTING"
    DELISTING = "DELISTING"
    BANKRUPTCY = "BANKRUPTCY"
    REORGANIZATION = "REORGANIZATION"


class ActionStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    CANCELLED = "CANCELLED"
    QUARANTINED = "QUARANTINED"


def _time(value: int | None, code: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)


def _decimal(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise InvariantViolation("INVALID_ADJUSTMENT_FACTOR")
    return value.normalize()


@dataclass(frozen=True, slots=True)
class CorporateActionVersion:
    action_id: UUID
    version: int
    instrument_id: UUID
    family: ActionFamily
    status: ActionStatus
    announcement_ns: int | None
    ex_date_ns: int | None
    record_date_ns: int | None
    effective_date_ns: int
    payable_date_ns: int | None
    expiration_date_ns: int | None
    first_seen_at_ns: int
    available_to_strategy_at_ns: int
    revision_time_ns: int
    source_id: str
    terms: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, UUID) or not isinstance(self.instrument_id, UUID):
            raise InvariantViolation("INVALID_ACTION_IDENTITY")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_ACTION_VERSION")
        if not isinstance(self.family, ActionFamily) or not isinstance(self.status, ActionStatus):
            raise InvariantViolation("INVALID_ACTION_ENUM")
        for value, code, optional in (
            (self.announcement_ns, "INVALID_ANNOUNCEMENT_TIME", True),
            (self.ex_date_ns, "INVALID_EX_DATE", True),
            (self.record_date_ns, "INVALID_RECORD_DATE", True),
            (self.effective_date_ns, "INVALID_EFFECTIVE_DATE", False),
            (self.payable_date_ns, "INVALID_PAYABLE_DATE", True),
            (self.expiration_date_ns, "INVALID_EXPIRATION_DATE", True),
            (self.first_seen_at_ns, "INVALID_FIRST_SEEN_TIME", False),
            (self.available_to_strategy_at_ns, "INVALID_AVAILABLE_TIME", False),
            (self.revision_time_ns, "INVALID_REVISION_TIME", False),
        ):
            _time(value, code, optional=optional)
        if self.available_to_strategy_at_ns < self.first_seen_at_ns:
            raise InvariantViolation("ACTION_AVAILABLE_BEFORE_FIRST_SEEN")
        if self.revision_time_ns < self.first_seen_at_ns:
            raise InvariantViolation("ACTION_REVISION_BEFORE_FIRST_SEEN")
        if not self.source_id.strip():
            raise InvariantViolation("MISSING_ACTION_SOURCE")
        if not isinstance(self.terms, Mapping):
            raise InvariantViolation("ACTION_TERMS_MUST_BE_MAPPING")
        normalized_terms = {str(key): value for key, value in self.terms.items()}
        canonical_sha256(normalized_terms)
        object.__setattr__(self, "terms", MappingProxyType(dict(sorted(normalized_terms.items()))))

    def canonical_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "version": self.version,
            "instrument_id": self.instrument_id,
            "family": self.family,
            "status": self.status,
            "announcement_ns": self.announcement_ns,
            "ex_date_ns": self.ex_date_ns,
            "record_date_ns": self.record_date_ns,
            "effective_date_ns": self.effective_date_ns,
            "payable_date_ns": self.payable_date_ns,
            "expiration_date_ns": self.expiration_date_ns,
            "first_seen_at_ns": self.first_seen_at_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "revision_time_ns": self.revision_time_ns,
            "source_id": self.source_id,
            "terms": self.terms,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class CorporateActionBook:
    live_trading_state = "HARD_LOCKED"

    def __init__(self) -> None:
        self._history: dict[UUID, list[CorporateActionVersion]] = {}
        self._hashes: dict[tuple[UUID, int], str] = {}

    def append(self, action: CorporateActionVersion) -> bool:
        key = (action.action_id, action.version)
        digest = action.sha256()
        existing = self._hashes.get(key)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(
                    f"ACTION_VERSION_CONFLICT:{action.action_id}:{action.version}"
                )
            return False
        history = self._history.setdefault(action.action_id, [])
        expected = len(history) + 1
        if action.version != expected:
            raise InvariantViolation(
                f"ACTION_VERSION_SEQUENCE:expected={expected}:actual={action.version}"
            )
        if history:
            previous = history[-1]
            if action.instrument_id != previous.instrument_id or action.family is not previous.family:
                raise InvariantViolation("ACTION_IDENTITY_MUTATION")
            if action.revision_time_ns < previous.revision_time_ns:
                raise InvariantViolation("ACTION_REVISION_TIME_REGRESSION")
        history.append(action)
        self._hashes[key] = digest
        return True

    def as_known(self, action_id: UUID, *, knowledge_time_ns: int) -> CorporateActionVersion | None:
        _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        visible = [
            action
            for action in self._history.get(action_id, ())
            if action.available_to_strategy_at_ns <= knowledge_time_ns
        ]
        return max(visible, key=lambda action: (action.revision_time_ns, action.version)) if visible else None

    def history(self, action_id: UUID) -> tuple[CorporateActionVersion, ...]:
        return tuple(self._history.get(action_id, ()))

    def effective_between(
        self,
        start_ns: int,
        end_ns: int,
        *,
        knowledge_time_ns: int,
    ) -> tuple[CorporateActionVersion, ...]:
        _time(start_ns, "INVALID_EFFECTIVE_RANGE")
        _time(end_ns, "INVALID_EFFECTIVE_RANGE")
        if end_ns < start_ns:
            raise InvariantViolation("INVALID_EFFECTIVE_RANGE")
        latest: list[CorporateActionVersion] = []
        for action_id in self._history:
            action = self.as_known(action_id, knowledge_time_ns=knowledge_time_ns)
            if (
                action is not None
                and action.status is not ActionStatus.CANCELLED
                and start_ns <= action.effective_date_ns <= end_ns
            ):
                latest.append(action)
        return tuple(sorted(latest, key=lambda action: (action.effective_date_ns, str(action.action_id))))


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    factor_id: UUID
    version: int
    instrument_id: UUID
    applies_before_ns: int
    factor: Decimal
    available_to_strategy_at_ns: int
    source_action_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.factor_id, UUID) or not isinstance(self.instrument_id, UUID):
            raise InvariantViolation("INVALID_ADJUSTMENT_IDENTITY")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_ADJUSTMENT_VERSION")
        _time(self.applies_before_ns, "INVALID_ADJUSTMENT_CUTOFF")
        _time(self.available_to_strategy_at_ns, "INVALID_AVAILABLE_TIME")
        object.__setattr__(self, "factor", _decimal(self.factor))
        if not _HEX64.fullmatch(self.source_action_sha256):
            raise InvariantViolation("INVALID_SOURCE_ACTION_SHA256")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "factor_id": self.factor_id,
            "version": self.version,
            "instrument_id": self.instrument_id,
            "applies_before_ns": self.applies_before_ns,
            "factor": self.factor,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "source_action_sha256": self.source_action_sha256,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class AdjustedPrice:
    raw_price: Price
    adjusted_price: Price
    factor_sha256: str
    knowledge_time_ns: int


class AdjustmentSeries:
    """Separate derived view; raw observations are never changed."""

    def __init__(self) -> None:
        self._history: dict[UUID, list[AdjustmentFactor]] = {}
        self._hashes: dict[tuple[UUID, int], str] = {}

    def append(self, factor: AdjustmentFactor) -> bool:
        key = (factor.factor_id, factor.version)
        digest = factor.sha256()
        existing = self._hashes.get(key)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(
                    f"ADJUSTMENT_VERSION_CONFLICT:{factor.factor_id}:{factor.version}"
                )
            return False
        history = self._history.setdefault(factor.factor_id, [])
        expected = len(history) + 1
        if factor.version != expected:
            raise InvariantViolation(
                f"ADJUSTMENT_VERSION_SEQUENCE:expected={expected}:actual={factor.version}"
            )
        if history and factor.instrument_id != history[-1].instrument_id:
            raise InvariantViolation("ADJUSTMENT_IDENTITY_MUTATION")
        history.append(factor)
        self._hashes[key] = digest
        return True

    def _visible(
        self,
        instrument_id: UUID,
        *,
        raw_time_ns: int,
        knowledge_time_ns: int,
    ) -> tuple[AdjustmentFactor, ...]:
        selected: list[AdjustmentFactor] = []
        for history in self._history.values():
            visible = [
                factor
                for factor in history
                if factor.instrument_id == instrument_id
                and raw_time_ns < factor.applies_before_ns
                and factor.available_to_strategy_at_ns <= knowledge_time_ns
            ]
            if visible:
                selected.append(max(visible, key=lambda factor: factor.version))
        return tuple(sorted(selected, key=lambda factor: (factor.applies_before_ns, str(factor.factor_id))))

    def adjust(
        self,
        raw_price: Price,
        instrument_id: UUID,
        *,
        raw_time_ns: int,
        knowledge_time_ns: int,
    ) -> AdjustedPrice | None:
        _time(raw_time_ns, "INVALID_RAW_TIME")
        _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        factors = self._visible(
            instrument_id,
            raw_time_ns=raw_time_ns,
            knowledge_time_ns=knowledge_time_ns,
        )
        if not factors:
            return None
        combined = Decimal("1")
        for factor in factors:
            combined *= factor.factor
        adjusted = Price.parse(
            raw_price.currency,
            raw_price.value * combined,
            tick_size=raw_price.tick_size,
        )
        factor_sha = (
            factors[0].sha256()
            if len(factors) == 1
            else canonical_sha256(tuple(factor.sha256() for factor in factors))
        )
        return AdjustedPrice(raw_price, adjusted, factor_sha, knowledge_time_ns)
