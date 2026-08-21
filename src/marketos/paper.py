"""Deterministic paper broker integrated with exact books and Risk Kernel."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import threading
from typing import Any

from .authoritative_books import C13GateDecision
from .canonical import canonical_sha256
from .errors import DuplicateConflict, ExecutionStateChanged, InvariantViolation
from .money import Money, Price, Quantity, RoundingPolicy
from .orders import ExecutionMode, OrderIntent, OrderSide, OrderState, OrderType
from .portfolio import PortfolioBook, PortfolioSnapshot
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

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class MarketView:
    """Immutable quote evidence used by one risk preparation."""

    execution: MarketSnapshot
    marks: tuple[MarketSnapshot, ...]

    def __post_init__(self) -> None:
        instruments = tuple(snapshot.instrument_id for snapshot in self.marks)
        if instruments != tuple(sorted(set(instruments))):
            raise InvariantViolation("MARKET_VIEW_MARKS_NOT_CANONICAL")
        if any(snapshot.bid.currency != self.execution.bid.currency for snapshot in self.marks):
            raise InvariantViolation("MARKET_VIEW_CURRENCY_MISMATCH")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "execution": self.execution,
            "marks": self.marks,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    intent: OrderIntent
    now_ns: int
    clock_quality: ClockQuality
    portfolio_snapshot: PortfolioSnapshot
    market_view: MarketView
    execution_price: Price
    estimated_fee: Money
    decision: RiskDecision
    intent_sha256: str
    portfolio_snapshot_sha256: str
    ledger_head_sha256: str
    market_view_sha256: str


@dataclass(frozen=True, slots=True)
class PendingExecution:
    intent: OrderIntent
    intent_sha256: str
    report: ExecutionReport
    updated_market: MarketSnapshot | None


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
    c13_gate_sha256: str
    portfolio_snapshot_sha256: str
    ledger_head_sha256: str
    market_view_sha256: str
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
            "c13_gate_sha256": self.c13_gate_sha256,
            "portfolio_snapshot_sha256": self.portfolio_snapshot_sha256,
            "ledger_head_sha256": self.ledger_head_sha256,
            "market_view_sha256": self.market_view_sha256,
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
        self._lock = threading.RLock()
        self._envelope_capability: object | None = None

    def _bind_envelope_capability(self, capability: object) -> None:
        with self._lock:
            if self._envelope_capability is not None:
                raise InvariantViolation("PAPER_BROKER_ALREADY_BOUND")
            self._envelope_capability = capability

    def update_market(self, snapshot: MarketSnapshot) -> None:
        with self._lock:
            existing = self._markets.get(snapshot.instrument_id)
            if existing is not None and snapshot.available_at_ns < existing.available_at_ns:
                raise InvariantViolation("STALE_MARKET_SNAPSHOT")
            self._markets[snapshot.instrument_id] = snapshot

    def market(self, instrument_id: str) -> MarketSnapshot:
        with self._lock:
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

    def _gross_notional(
        self,
        portfolio_snapshot: PortfolioSnapshot,
        market_view: MarketView,
    ) -> Money:
        total = Money.zero(self.portfolio.base_currency)
        marks = {snapshot.instrument_id: snapshot for snapshot in market_view.marks}
        for position in portfolio_snapshot.positions:
            if position.quantity.value == 0:
                continue
            snapshot = marks.get(position.instrument_id)
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
        c13_gate_sha256: str,
        portfolio_snapshot_sha256: str,
        ledger_head_sha256: str,
        market_view_sha256: str,
    ) -> ExecutionReport:
        payload: dict[str, Any] = {
            "intent_id": intent.intent_id,
            "state": state,
            "risk_decision": decision,
            "fills": fills,
            "remaining_quantity": remaining,
            "reasons": reasons,
            "inserted": inserted,
            "c13_gate_sha256": c13_gate_sha256,
            "portfolio_snapshot_sha256": portfolio_snapshot_sha256,
            "ledger_head_sha256": ledger_head_sha256,
            "market_view_sha256": market_view_sha256,
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
            c13_gate_sha256=c13_gate_sha256,
            portfolio_snapshot_sha256=portfolio_snapshot_sha256,
            ledger_head_sha256=ledger_head_sha256,
            market_view_sha256=market_view_sha256,
            report_sha256=digest,
        )

    def _market_view(
        self,
        intent: OrderIntent,
        portfolio_snapshot: PortfolioSnapshot,
    ) -> MarketView:
        execution = self.market(intent.instrument_id)
        marks: list[MarketSnapshot] = []
        for position in portfolio_snapshot.positions:
            if position.quantity.value == 0:
                continue
            marks.append(self.market(position.instrument_id))
        marks.sort(key=lambda snapshot: snapshot.instrument_id)
        return MarketView(execution=execution, marks=tuple(marks))

    def _prepare(
        self,
        intent: OrderIntent,
        *,
        now_ns: int,
        clock_quality: ClockQuality,
    ) -> PreparedExecution:
        """Capture one immutable portfolio/market evidence set for the envelope."""
        with self._lock:
            portfolio_snapshot = self.portfolio.snapshot()
            market_view = self._market_view(intent, portfolio_snapshot)
            execution_price = self._execution_price(intent, market_view.execution)
            estimated_fee = self._fee(execution_price, intent.quantity)
            portfolio_snapshot_sha256 = portfolio_snapshot.sha256()
            ledger_head_sha256 = portfolio_snapshot.ledger_sha256
            market_view_sha256 = market_view.sha256()
            market_evidence = {
                snapshot.instrument_id: snapshot.available_at_ns
                for snapshot in (market_view.execution, *market_view.marks)
            }
            decision = self.risk_kernel.evaluate(
                intent,
                RiskContext(
                    now_ns=now_ns,
                    data_available_at_ns=market_view.execution.available_at_ns,
                    portfolio_snapshot_sha256=portfolio_snapshot_sha256,
                    ledger_head_sha256=ledger_head_sha256,
                    market_view_sha256=market_view_sha256,
                    clock_quality=clock_quality,
                    cash=portfolio_snapshot.cash,
                    current_position=next(
                        (
                            position.quantity
                            for position in portfolio_snapshot.positions
                            if position.instrument_id == intent.instrument_id
                        ),
                        Quantity.parse("0"),
                    ),
                    current_gross_notional=self._gross_notional(
                        portfolio_snapshot,
                        market_view,
                    ),
                    mark_price=execution_price,
                    estimated_fee=estimated_fee,
                    market_evidence_available_at_ns=tuple(sorted(market_evidence.items())),
                ),
            )
            return PreparedExecution(
                intent=intent,
                now_ns=now_ns,
                clock_quality=clock_quality,
                portfolio_snapshot=portfolio_snapshot,
                market_view=market_view,
                execution_price=execution_price,
                estimated_fee=estimated_fee,
                decision=decision,
                intent_sha256=intent.sha256(),
                portfolio_snapshot_sha256=portfolio_snapshot_sha256,
                ledger_head_sha256=ledger_head_sha256,
                market_view_sha256=market_view_sha256,
            )

    def _assert_capability(self, capability: object) -> None:
        if self._envelope_capability is None or capability is not self._envelope_capability:
            raise InvariantViolation("PAPER_BROKER_CAPABILITY_INVALID")

    def _commit_authorized(
        self,
        prepared: PreparedExecution,
        *,
        capability: object,
        transaction_owner: object,
        c13_gate: C13GateDecision,
    ) -> PendingExecution:
        """Apply one prepared fill; the caller owns the durable transaction."""
        with self._lock:
            self._assert_capability(capability)
            ledger = getattr(self.portfolio, "ledger", None)
            if (
                ledger is None
                or not getattr(ledger, "_execution_transaction_active", False)
                or getattr(ledger, "_execution_transaction_owner", None) is not transaction_owner
            ):
                raise InvariantViolation("EXECUTION_TRANSACTION_REQUIRED")
            if not isinstance(prepared, PreparedExecution):
                raise InvariantViolation("INVALID_PREPARED_EXECUTION")
            if prepared.intent_sha256 != prepared.intent.sha256():
                raise InvariantViolation("PREPARED_INTENT_INTEGRITY_FAILURE")
            if (
                prepared.portfolio_snapshot_sha256 != prepared.portfolio_snapshot.sha256()
                or prepared.ledger_head_sha256 != prepared.portfolio_snapshot.ledger_sha256
                or prepared.market_view_sha256 != prepared.market_view.sha256()
            ):
                raise InvariantViolation("PREPARED_SOURCE_INTEGRITY_FAILURE")
            if not isinstance(c13_gate, C13GateDecision):
                raise InvariantViolation("INVALID_C13_GATE_DECISION")
            if canonical_sha256(c13_gate.canonical_dict()) != c13_gate.decision_sha256:
                raise InvariantViolation("C13_GATE_INTEGRITY_FAILURE")
            if (
                c13_gate.action is not RiskAction.ALLOW
                or c13_gate.intent_id != prepared.intent.intent_id
                or c13_gate.portfolio_snapshot_sha256 != prepared.portfolio_snapshot_sha256
                or c13_gate.ledger_head_sha256 != prepared.ledger_head_sha256
                or c13_gate.market_view_sha256 != prepared.market_view_sha256
            ):
                raise InvariantViolation("C13_GATE_SOURCE_BINDING_FAILURE")
            current_snapshot = self.portfolio.snapshot()
            if current_snapshot != prepared.portfolio_snapshot:
                raise ExecutionStateChanged("EXECUTION_PORTFOLIO_CHANGED")
            current_view = self._market_view(prepared.intent, current_snapshot)
            if current_view.sha256() != prepared.market_view_sha256:
                raise ExecutionStateChanged("EXECUTION_MARKET_VIEW_CHANGED")
            execution_price = self._execution_price(
                prepared.intent,
                current_view.execution,
            )
            if execution_price != prepared.execution_price:
                raise ExecutionStateChanged("EXECUTION_QUOTE_CHANGED")
            estimated_fee = self._fee(execution_price, prepared.intent.quantity)
            if estimated_fee != prepared.estimated_fee:
                raise ExecutionStateChanged("EXECUTION_FEE_CHANGED")
            current_position = next(
                (
                    position.quantity
                    for position in current_snapshot.positions
                    if position.instrument_id == prepared.intent.instrument_id
                ),
                Quantity.parse("0"),
            )
            market_evidence = {
                snapshot.instrument_id: snapshot.available_at_ns
                for snapshot in (current_view.execution, *current_view.marks)
            }
            recomputed_decision = self.risk_kernel.evaluate(
                prepared.intent,
                RiskContext(
                    now_ns=prepared.now_ns,
                    data_available_at_ns=current_view.execution.available_at_ns,
                    portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                    ledger_head_sha256=prepared.ledger_head_sha256,
                    market_view_sha256=prepared.market_view_sha256,
                    clock_quality=prepared.clock_quality,
                    cash=current_snapshot.cash,
                    current_position=current_position,
                    current_gross_notional=self._gross_notional(
                        current_snapshot,
                        current_view,
                    ),
                    mark_price=execution_price,
                    estimated_fee=estimated_fee,
                    market_evidence_available_at_ns=tuple(sorted(market_evidence.items())),
                ),
            )
            if recomputed_decision != prepared.decision:
                raise InvariantViolation("PREPARED_RISK_DECISION_INTEGRITY_FAILURE")
            if prepared.decision.action is not RiskAction.ALLOW:
                raise InvariantViolation("PREPARED_EXECUTION_NOT_ALLOWED")

            c13_gate_sha256 = c13_gate.sha256()

            intent = prepared.intent
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
                        decision=prepared.decision,
                        fills=(),
                        remaining=intent.quantity,
                        reasons=("LIMIT_NOT_MARKETABLE",),
                        inserted=True,
                        c13_gate_sha256=c13_gate_sha256,
                        portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                        ledger_head_sha256=prepared.ledger_head_sha256,
                        market_view_sha256=prepared.market_view_sha256,
                    )
                    return PendingExecution(intent, prepared.intent_sha256, report, None)

            visible = (
                current_view.execution.ask_size
                if intent.side is OrderSide.BUY
                else current_view.execution.bid_size
            )
            fill_value = min(intent.quantity.value, visible.value)
            if fill_value <= 0:
                report = self._report(
                    intent=intent,
                    state=OrderState.CANCELLED,
                    decision=prepared.decision,
                    fills=(),
                    remaining=intent.quantity,
                    reasons=("NO_VISIBLE_LIQUIDITY",),
                    inserted=True,
                    c13_gate_sha256=c13_gate_sha256,
                    portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                    ledger_head_sha256=prepared.ledger_head_sha256,
                    market_view_sha256=prepared.market_view_sha256,
                )
                return PendingExecution(intent, prepared.intent_sha256, report, None)

            fill_quantity = Quantity.positive(fill_value)
            fee = self._fee(execution_price, fill_quantity)
            fill = Fill(
                fill_id=f"fill:{intent.idempotency_key}:0",
                intent_id=intent.intent_id,
                instrument_id=intent.instrument_id,
                side=intent.side,
                quantity=fill_quantity,
                price=execution_price,
                fee=fee,
                occurred_at_ns=prepared.now_ns,
            )
            if intent.side is OrderSide.BUY:
                application = self.portfolio.buy(
                    fill.fill_id,
                    intent.instrument_id,
                    fill.quantity,
                    fill.price,
                    fill.fee,
                    occurred_at_ns=prepared.now_ns,
                )
                updated_snapshot = replace(
                    current_view.execution,
                    ask_size=Quantity.parse(current_view.execution.ask_size.value - fill_value),
                )
            else:
                application = self.portfolio.sell(
                    fill.fill_id,
                    intent.instrument_id,
                    fill.quantity,
                    fill.price,
                    fill.fee,
                    occurred_at_ns=prepared.now_ns,
                )
                updated_snapshot = replace(
                    current_view.execution,
                    bid_size=Quantity.parse(current_view.execution.bid_size.value - fill_value),
                )
            if not application.inserted:
                raise ExecutionStateChanged("DUPLICATE_FILL_ENTRY")

            remaining = Quantity.parse(intent.quantity.value - fill_value)
            state = OrderState.FILLED if remaining.value == 0 else OrderState.PARTIALLY_FILLED
            report = self._report(
                intent=intent,
                state=state,
                decision=prepared.decision,
                fills=(fill,),
                remaining=remaining,
                reasons=(),
                inserted=True,
                c13_gate_sha256=c13_gate_sha256,
                portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                ledger_head_sha256=prepared.ledger_head_sha256,
                market_view_sha256=prepared.market_view_sha256,
            )
            return PendingExecution(intent, prepared.intent_sha256, report, updated_snapshot)

    def _finalize_pending(self, pending: PendingExecution, *, capability: object) -> ExecutionReport:
        with self._lock:
            self._assert_capability(capability)
            if pending.updated_market is not None:
                self._markets[pending.updated_market.instrument_id] = pending.updated_market
            self._reports[pending.intent.idempotency_key] = (
                pending.intent_sha256,
                pending.report,
            )
            return pending.report

    def submit(self, *args: Any, **kwargs: Any) -> ExecutionReport:
        del args, kwargs
        raise InvariantViolation("PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN")
