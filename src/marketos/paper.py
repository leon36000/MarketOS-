"""Deterministic paper broker integrated with exact books and Risk Kernel."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

from .canonical import canonical_sha256
from .errors import DuplicateConflict, InvariantViolation
from .money import Money, Price, Quantity, RoundingPolicy
from .orders import ExecutionMode, OrderIntent, OrderSide, OrderState, OrderType
from .portfolio import PortfolioBook
from .risk import RiskAction, RiskContext, RiskDecision, RiskKernel
from .time import ClockQuality


def _decimal_bps(value: str | int | Decimal, field: str) -> Decimal:
    if isinstance(value, float):
        raise InvariantViolation("FLOAT_FORBIDDEN")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise InvariantViolation(f"INVALID_{field}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise InvariantViolation(f"INVALID_{field}")
    return parsed


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    instrument_id: str
    bid: Price
    ask: Price
    bid_size: Quantity
    ask_size: Quantity
    available_at_ns: int
    source_event_id: str

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.source_event_id.strip():
            raise InvariantViolation("MISSING_MARKET_SNAPSHOT_ID")
        if self.bid.currency != self.ask.currency:
            raise InvariantViolation("MARKET_CURRENCY_MISMATCH")
        if self.bid.tick_size != self.ask.tick_size:
            raise InvariantViolation("MARKET_TICK_MISMATCH")
        if self.bid.value > self.ask.value:
            raise InvariantViolation("CROSSED_MARKET_SNAPSHOT")
        if isinstance(self.available_at_ns, bool) or not isinstance(self.available_at_ns, int) or self.available_at_ns < 0:
            raise InvariantViolation("INVALID_MARKET_AVAILABLE_TIME")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "available_at_ns": self.available_at_ns,
            "source_event_id": self.source_event_id,
        }


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    intent_id: str
    instrument_id: str
    side: OrderSide
    quantity: Quantity
    price: Price
    fee: Money
    occurred_at_ns: int
    mode: ExecutionMode = ExecutionMode.PAPER

    def __post_init__(self) -> None:
        if not self.fill_id.strip() or not self.intent_id.strip():
            raise InvariantViolation("MISSING_FILL_ID")
        if self.quantity.value <= 0:
            raise InvariantViolation("POSITIVE_QUANTITY_REQUIRED")
        if self.fee.currency != self.price.currency or self.fee.minor_units < 0:
            raise InvariantViolation("INVALID_FILL_FEE")
        if self.mode is not ExecutionMode.PAPER:
            raise InvariantViolation("PAPER_FILL_MODE_REQUIRED")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "fill_id": self.fill_id,
            "intent_id": self.intent_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "fee": self.fee,
            "occurred_at_ns": self.occurred_at_ns,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    intent_id: str
    state: OrderState
    risk_decision: RiskDecision
    fills: tuple[Fill, ...]
    remaining_quantity: Quantity
    reasons: tuple[str, ...]
    inserted: bool
    report_sha256: str
    live_trading_state: str = "HARD_LOCKED"

    def canonical_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "intent_id": self.intent_id,
            "state": self.state,
            "risk_decision": self.risk_decision,
            "fills": self.fills,
            "remaining_quantity": self.remaining_quantity,
            "reasons": self.reasons,
            "inserted": self.inserted,
            "live_trading_state": self.live_trading_state,
        }
        if include_hash:
            value["report_sha256"] = self.report_sha256
        return value


class PaperBroker:
    def __init__(
        self,
        *,
        portfolio: PortfolioBook,
        risk_kernel: RiskKernel,
        fee_bps: str | int | Decimal,
        slippage_bps: str | int | Decimal,
    ) -> None:
        self.portfolio = portfolio
        self.risk_kernel = risk_kernel
        self.fee_bps = _decimal_bps(fee_bps, "FEE_BPS")
        self.slippage_bps = _decimal_bps(slippage_bps, "SLIPPAGE_BPS")
        self._markets: dict[str, MarketSnapshot] = {}
        self._reports: dict[str, tuple[str, ExecutionReport]] = {}

    def update_market(self, snapshot: MarketSnapshot) -> None:
        existing = self._markets.get(snapshot.instrument_id)
        if existing is not None and snapshot.available_at_ns < existing.available_at_ns:
            raise InvariantViolation("STALE_MARKET_SNAPSHOT")
        self._markets[snapshot.instrument_id] = snapshot

    def market(self, instrument_id: str) -> MarketSnapshot:
        try:
            return self._markets[instrument_id]
        except KeyError as exc:
            raise InvariantViolation(f"MISSING_MARKET_SNAPSHOT:{instrument_id}") from exc

    def _execution_price(self, intent: OrderIntent, snapshot: MarketSnapshot) -> Price:
        base = snapshot.ask if intent.side is OrderSide.BUY else snapshot.bid
        multiplier = Decimal("1") + (
            self.slippage_bps / Decimal("10000")
            if intent.side is OrderSide.BUY
            else -(self.slippage_bps / Decimal("10000"))
        )
        raw = base.value * multiplier
        rounding = ROUND_CEILING if intent.side is OrderSide.BUY else ROUND_FLOOR
        ticks = (raw / base.tick_size).to_integral_value(rounding=rounding)
        return Price.parse(base.currency, ticks * base.tick_size, tick_size=base.tick_size)

    def _fee(self, price: Price, quantity: Quantity) -> Money:
        notional = price.notional(quantity, rounding=RoundingPolicy.HALF_EVEN)
        return Money.from_decimal(
            price.currency,
            notional.to_decimal() * self.fee_bps / Decimal("10000"),
            rounding=RoundingPolicy.HALF_UP,
        )

    def _gross_notional(self) -> Money:
        total = Money.zero(self.portfolio.base_currency)
        for position in self.portfolio.snapshot().positions:
            if position.quantity.value == 0:
                continue
            snapshot = self._markets.get(position.instrument_id)
            if snapshot is None:
                raise InvariantViolation(f"MISSING_MARK_FOR_POSITION:{position.instrument_id}")
            mid = (snapshot.bid.value + snapshot.ask.value) / Decimal("2")
            amount = Money.from_decimal(
                self.portfolio.base_currency,
                mid * position.quantity.value,
                rounding=RoundingPolicy.HALF_EVEN,
            )
            total = total + Money(total.currency, abs(amount.minor_units))
        return total

    @staticmethod
    def _report(
        *,
        intent: OrderIntent,
        state: OrderState,
        decision: RiskDecision,
        fills: tuple[Fill, ...],
        remaining: Quantity,
        reasons: tuple[str, ...],
        inserted: bool,
    ) -> ExecutionReport:
        payload: dict[str, Any] = {
            "intent_id": intent.intent_id,
            "state": state,
            "risk_decision": decision,
            "fills": fills,
            "remaining_quantity": remaining,
            "reasons": reasons,
            "inserted": True,
            "live_trading_state": "HARD_LOCKED",
        }
        digest = canonical_sha256(payload)
        return ExecutionReport(
            intent_id=intent.intent_id,
            state=state,
            risk_decision=decision,
            fills=fills,
            remaining_quantity=remaining,
            reasons=reasons,
            inserted=inserted,
            report_sha256=digest,
        )

    def submit(
        self,
        intent: OrderIntent,
        *,
        now_ns: int,
        clock_quality: ClockQuality,
        books_reconciled: bool,
    ) -> ExecutionReport:
        intent_hash = intent.sha256()
        existing = self._reports.get(intent.idempotency_key)
        if existing is not None:
            existing_hash, report = existing
            if existing_hash != intent_hash:
                raise DuplicateConflict(f"IDEMPOTENCY_KEY_CONFLICT:{intent.idempotency_key}")
            return replace(report, inserted=False)

        snapshot = self.market(intent.instrument_id)
        execution_price = self._execution_price(intent, snapshot)
        estimated_fee = self._fee(execution_price, intent.quantity)
        decision = self.risk_kernel.evaluate(
            intent,
            RiskContext(
                now_ns=now_ns,
                data_available_at_ns=snapshot.available_at_ns,
                books_reconciled=books_reconciled,
                clock_quality=clock_quality,
                cash=self.portfolio.cash(),
                current_position=self.portfolio.position(intent.instrument_id).quantity,
                current_gross_notional=self._gross_notional(),
                mark_price=execution_price,
                estimated_fee=estimated_fee,
            ),
        )
        if decision.action is RiskAction.NO_TRADE:
            report = self._report(
                intent=intent,
                state=OrderState.REJECTED,
                decision=decision,
                fills=(),
                remaining=intent.quantity,
                reasons=decision.reasons,
                inserted=True,
            )
            self._reports[intent.idempotency_key] = (intent_hash, report)
            return report

        if intent.mode is not ExecutionMode.PAPER:
            report = self._report(
                intent=intent,
                state=OrderState.CANCELLED,
                decision=decision,
                fills=(),
                remaining=intent.quantity,
                reasons=("SHADOW_MODE_NO_EXECUTION",),
                inserted=True,
            )
            self._reports[intent.idempotency_key] = (intent_hash, report)
            return report

        if intent.order_type is OrderType.LIMIT:
            assert intent.limit_price is not None
            marketable = (
                execution_price.value <= intent.limit_price.value
                if intent.side is OrderSide.BUY
                else execution_price.value >= intent.limit_price.value
            )
            if not marketable:
                report = self._report(
                    intent=intent,
                    state=OrderState.CANCELLED,
                    decision=decision,
                    fills=(),
                    remaining=intent.quantity,
                    reasons=("LIMIT_NOT_MARKETABLE",),
                    inserted=True,
                )
                self._reports[intent.idempotency_key] = (intent_hash, report)
                return report

        visible = snapshot.ask_size if intent.side is OrderSide.BUY else snapshot.bid_size
        fill_value = min(intent.quantity.value, visible.value)
        if fill_value <= 0:
            report = self._report(
                intent=intent,
                state=OrderState.CANCELLED,
                decision=decision,
                fills=(),
                remaining=intent.quantity,
                reasons=("NO_VISIBLE_LIQUIDITY",),
                inserted=True,
            )
            self._reports[intent.idempotency_key] = (intent_hash, report)
            return report

        fill_quantity = Quantity.positive(fill_value)
        fee = self._fee(execution_price, fill_quantity)
        fill = Fill(
            fill_id=f"fill:{intent.intent_id}:0",
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=fill_quantity,
            price=execution_price,
            fee=fee,
            occurred_at_ns=now_ns,
        )
        if intent.side is OrderSide.BUY:
            self.portfolio.buy(
                fill.fill_id,
                intent.instrument_id,
                fill.quantity,
                fill.price,
                fill.fee,
                occurred_at_ns=now_ns,
            )
            updated_snapshot = replace(snapshot, ask_size=Quantity.parse(snapshot.ask_size.value - fill_value))
        else:
            self.portfolio.sell(
                fill.fill_id,
                intent.instrument_id,
                fill.quantity,
                fill.price,
                fill.fee,
                occurred_at_ns=now_ns,
            )
            updated_snapshot = replace(snapshot, bid_size=Quantity.parse(snapshot.bid_size.value - fill_value))
        self._markets[intent.instrument_id] = updated_snapshot

        remaining = Quantity.parse(intent.quantity.value - fill_value)
        state = OrderState.FILLED if remaining.value == 0 else OrderState.PARTIALLY_FILLED
        report = self._report(
            intent=intent,
            state=state,
            decision=decision,
            fills=(fill,),
            remaining=remaining,
            reasons=(),
            inserted=True,
        )
        self._reports[intent.idempotency_key] = (intent_hash, report)
        return report
