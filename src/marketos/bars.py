"""Deterministic point-in-time trade-bar construction.

Bars are derived views over already admitted canonical trade observations.  A
bar is emitted only after its interval has closed at the requested knowledge
cutoff, and late arrivals change only later point-in-time rebuilds.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable
from uuid import UUID

from .canonical import canonical_sha256
from .errors import DomainError, InvariantViolation
from .marketdata import (
    MarketObservation,
    ObservationKind,
    ObservationStatus,
    TradePayload,
)
from .money import Price, Quantity
from .rights import RightsPolicy


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BarDerivationDenied(DomainError):
    """Raised when data rights do not permit the requested derived view."""


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


@dataclass(frozen=True, slots=True)
class TradeBar:
    listing_id: UUID
    venue_id: UUID
    interval_start_ns: int
    interval_end_ns: int
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Quantity
    trade_count: int
    available_to_strategy_at_ns: int
    input_root_sha256: str
    rights_policy_sha256: str
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        if not isinstance(self.listing_id, UUID) or not isinstance(self.venue_id, UUID):
            raise InvariantViolation("INVALID_BAR_IDENTITY")
        _nonnegative_int(self.interval_start_ns, "INVALID_BAR_START")
        _nonnegative_int(self.interval_end_ns, "INVALID_BAR_END")
        _nonnegative_int(self.available_to_strategy_at_ns, "INVALID_BAR_AVAILABLE_TIME")
        if self.interval_end_ns <= self.interval_start_ns:
            raise InvariantViolation("INVALID_BAR_INTERVAL")
        if self.available_to_strategy_at_ns < self.interval_end_ns:
            raise InvariantViolation("BAR_AVAILABLE_BEFORE_CLOSE")
        if isinstance(self.trade_count, bool) or not isinstance(self.trade_count, int) or self.trade_count < 1:
            raise InvariantViolation("INVALID_BAR_TRADE_COUNT")
        if self.volume.value <= 0:
            raise InvariantViolation("INVALID_BAR_VOLUME")
        currency = self.open.currency
        tick = self.open.tick_size
        for price in (self.high, self.low, self.close):
            if price.currency != currency:
                raise InvariantViolation("BAR_CURRENCY_MISMATCH")
            if price.tick_size != tick:
                raise InvariantViolation("BAR_TICK_SIZE_MISMATCH")
        if self.high.value < max(self.open.value, self.close.value, self.low.value):
            raise InvariantViolation("INVALID_BAR_HIGH")
        if self.low.value > min(self.open.value, self.close.value, self.high.value):
            raise InvariantViolation("INVALID_BAR_LOW")
        if not _HEX64.fullmatch(self.input_root_sha256):
            raise InvariantViolation("INVALID_BAR_INPUT_ROOT")
        if not _HEX64.fullmatch(self.rights_policy_sha256):
            raise InvariantViolation("INVALID_BAR_RIGHTS_POLICY_HASH")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("BAR_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "listing_id": self.listing_id,
            "venue_id": self.venue_id,
            "interval_start_ns": self.interval_start_ns,
            "interval_end_ns": self.interval_end_ns,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trade_count": self.trade_count,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "input_root_sha256": self.input_root_sha256,
            "rights_policy_sha256": self.rights_policy_sha256,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


def _latest_known_trades(
    observations: Iterable[MarketObservation],
    *,
    knowledge_time_ns: int,
) -> tuple[MarketObservation, ...]:
    seen_versions: set[tuple[str, int]] = set()
    identities: dict[str, tuple[object, ...]] = {}
    latest: dict[str, MarketObservation] = {}
    for observation in observations:
        key = (observation.observation_id, observation.version)
        if key in seen_versions:
            raise InvariantViolation(
                f"DUPLICATE_TRADE_OBSERVATION:{observation.observation_id}:{observation.version}"
            )
        seen_versions.add(key)
        if observation.kind is not ObservationKind.TRADE:
            continue
        if observation.time.available_at_ns > knowledge_time_ns:
            continue
        identity = (
            observation.kind,
            observation.listing_id,
            observation.venue_id,
            observation.source_id,
            observation.channel_id,
            observation.time.event_time_ns,
        )
        previous_identity = identities.setdefault(observation.observation_id, identity)
        if previous_identity != identity:
            raise InvariantViolation(
                f"BAR_OBSERVATION_IDENTITY_MUTATION:{observation.observation_id}"
            )
        previous = latest.get(observation.observation_id)
        if previous is None or (
            observation.time.available_at_ns,
            observation.version,
        ) > (
            previous.time.available_at_ns,
            previous.version,
        ):
            latest[observation.observation_id] = observation
    return tuple(
        observation
        for observation in latest.values()
        if observation.status is not ObservationStatus.CANCELLED
    )


def build_trade_bars(
    observations: Iterable[MarketObservation],
    *,
    interval_ns: int,
    knowledge_time_ns: int,
    rights_policy: RightsPolicy,
) -> tuple[TradeBar, ...]:
    """Build exact, deterministic OHLCV bars as known at a historical cutoff."""

    if isinstance(interval_ns, bool) or not isinstance(interval_ns, int) or interval_ns <= 0:
        raise InvariantViolation("INVALID_BAR_INTERVAL_SIZE")
    _nonnegative_int(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
    for capability in ("non_display", "historical_replay", "derived_data"):
        if not rights_policy.allows(capability):
            raise BarDerivationDenied(
                f"BAR_DERIVATION_RIGHT_DENIED:{rights_policy.policy_id}:{capability}"
            )
    rights_policy_sha256 = rights_policy.sha256()

    trades = _latest_known_trades(
        observations,
        knowledge_time_ns=knowledge_time_ns,
    )
    ordered = sorted(
        trades,
        key=lambda item: (
            item.time.event_time_ns,
            item.source_id,
            item.channel_id,
            item.source_sequence,
            item.observation_id,
            item.version,
        ),
    )

    buckets: dict[tuple[UUID, UUID, int], list[MarketObservation]] = {}
    for observation in ordered:
        bucket_start = (observation.time.event_time_ns // interval_ns) * interval_ns
        bucket_end = bucket_start + interval_ns
        if bucket_end > knowledge_time_ns:
            continue
        buckets.setdefault(
            (observation.listing_id, observation.venue_id, bucket_start),
            [],
        ).append(observation)

    bars: list[TradeBar] = []
    for (listing_id, venue_id, bucket_start), bucket in sorted(
        buckets.items(),
        key=lambda item: (item[0][2], str(item[0][0]), str(item[0][1])),
    ):
        payloads: list[TradePayload] = []
        for observation in bucket:
            if not isinstance(observation.payload, TradePayload):
                raise InvariantViolation("TRADE_PAYLOAD_REQUIRED")
            payloads.append(observation.payload)
        first_price = payloads[0].price
        for payload in payloads[1:]:
            if payload.price.currency != first_price.currency:
                raise InvariantViolation("BAR_INPUT_CURRENCY_MISMATCH")
            if payload.price.tick_size != first_price.tick_size:
                raise InvariantViolation("BAR_INPUT_TICK_SIZE_MISMATCH")

        prices = [payload.price for payload in payloads]
        volume_value = sum((payload.size.value for payload in payloads), Decimal("0"))
        interval_end = bucket_start + interval_ns
        available = max(
            interval_end,
            max(observation.time.available_at_ns for observation in bucket),
        )
        input_root = canonical_sha256(
            tuple(observation.sha256() for observation in bucket)
        )
        bars.append(
            TradeBar(
                listing_id=listing_id,
                venue_id=venue_id,
                interval_start_ns=bucket_start,
                interval_end_ns=interval_end,
                open=prices[0],
                high=max(prices, key=lambda price: price.value),
                low=min(prices, key=lambda price: price.value),
                close=prices[-1],
                volume=Quantity.positive(volume_value),
                trade_count=len(bucket),
                available_to_strategy_at_ns=available,
                input_root_sha256=input_root,
                rights_policy_sha256=rights_policy_sha256,
            )
        )
    return tuple(bars)
