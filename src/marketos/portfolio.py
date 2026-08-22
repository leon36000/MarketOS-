"""Exact paper portfolio and average-cost position book."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .ledger import JournalEntry, Ledger, Posting, PostingSide
from .money import Money, Price, Quantity, RoundingPolicy


@dataclass(frozen=True, slots=True)
class Position:
    instrument_id: str
    quantity: Quantity
    average_cost: Decimal
    currency: str

    def canonical_dict(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "average_cost": self.average_cost,
            "currency": self.currency,
        }


@dataclass(frozen=True, slots=True)
class TradeApplication:
    trade_id: str
    inserted: bool
    realized_pnl: Money
    journal_entry_id: str


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    base_currency: str
    cash: Money
    positions: tuple[Position, ...]
    realized_pnl: Money
    ledger_sha256: str

    def canonical_dict(self) -> dict[str, object]:
        return {
            "base_currency": self.base_currency,
            "cash": self.cash,
            "positions": self.positions,
            "realized_pnl": self.realized_pnl,
            "ledger_sha256": self.ledger_sha256,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class PortfolioBook:
    def __init__(self, *, base_currency: str, ledger: Ledger | None = None) -> None:
        self.base_currency = Money.zero(base_currency).currency
        self.ledger = ledger or Ledger()
        self._positions: dict[str, Position] = {}
        self._realized = Money.zero(self.base_currency)

    @property
    def cash_account(self) -> str:
        return f"asset:cash:{self.base_currency}"

    def fund(self, entry_id: str, amount: Money, *, occurred_at_ns: int) -> bool:
        self._require_currency(amount.currency)
        if amount.minor_units <= 0:
            raise InvariantViolation("FUNDING_MUST_BE_POSITIVE")
        return self.ledger.post(
            JournalEntry(
                entry_id=entry_id,
                occurred_at_ns=occurred_at_ns,
                description="Portfolio funding",
                postings=(
                    Posting(self.cash_account, PostingSide.DEBIT, amount),
                    Posting(f"equity:capital:{self.base_currency}", PostingSide.CREDIT, amount),
                ),
            )
        )

    def _require_currency(self, currency: str) -> None:
        if currency.upper() != self.base_currency:
            raise InvariantViolation("PORTFOLIO_CURRENCY_MISMATCH")

    def cash(self) -> Money:
        return self.ledger.balance(self.cash_account, self.base_currency)

    def realized_pnl(self) -> Money:
        return self._realized

    def position(self, instrument_id: str) -> Position:
        return self._positions.get(
            instrument_id,
            Position(instrument_id, Quantity.parse("0"), Decimal("0"), self.base_currency),
        )

    def buy(
        self,
        trade_id: str,
        instrument_id: str,
        quantity: Quantity,
        price: Price,
        fee: Money,
        *,
        occurred_at_ns: int,
    ) -> TradeApplication:
        self._require_currency(price.currency)
        self._require_currency(fee.currency)
        if quantity.value <= 0:
            raise InvariantViolation("POSITIVE_QUANTITY_REQUIRED")
        if fee.minor_units < 0:
            raise InvariantViolation("NEGATIVE_FEE")
        notional = price.notional(quantity, rounding=RoundingPolicy.HALF_EVEN)
        total = notional + fee
        if self.cash() < total:
            raise InvariantViolation("INSUFFICIENT_CASH")
        postings = [
            Posting(f"asset:inventory:{instrument_id}", PostingSide.DEBIT, notional),
            Posting(self.cash_account, PostingSide.CREDIT, total),
        ]
        if fee.minor_units:
            postings.insert(1, Posting(f"expense:fees:{self.base_currency}", PostingSide.DEBIT, fee))
        entry = JournalEntry(
            entry_id=trade_id,
            occurred_at_ns=occurred_at_ns,
            description=f"BUY {instrument_id}",
            postings=tuple(postings),
        )
        inserted = self.ledger.post(entry)
        if not inserted:
            return TradeApplication(trade_id, False, Money.zero(self.base_currency), trade_id)
        current = self.position(instrument_id)
        new_quantity = current.quantity.value + quantity.value
        weighted_cost = current.average_cost * current.quantity.value + price.value * quantity.value
        average = weighted_cost / new_quantity
        self._positions[instrument_id] = Position(
            instrument_id,
            Quantity.parse(new_quantity),
            average.normalize(),
            self.base_currency,
        )
        return TradeApplication(trade_id, True, Money.zero(self.base_currency), trade_id)

    def sell(
        self,
        trade_id: str,
        instrument_id: str,
        quantity: Quantity,
        price: Price,
        fee: Money,
        *,
        occurred_at_ns: int,
    ) -> TradeApplication:
        self._require_currency(price.currency)
        self._require_currency(fee.currency)
        current = self.position(instrument_id)
        if quantity.value <= 0:
            raise InvariantViolation("POSITIVE_QUANTITY_REQUIRED")
        if current.quantity.value < quantity.value:
            raise InvariantViolation("INSUFFICIENT_POSITION")
        if fee.minor_units < 0:
            raise InvariantViolation("NEGATIVE_FEE")
        proceeds = price.notional(quantity, rounding=RoundingPolicy.HALF_EVEN)
        if fee > proceeds:
            raise InvariantViolation("FEE_EXCEEDS_PROCEEDS")
        cost_basis = Money.from_decimal(
            self.base_currency,
            current.average_cost * quantity.value,
            rounding=RoundingPolicy.HALF_EVEN,
        )
        cash_received = proceeds - fee
        gross_realized = proceeds - cost_basis
        realized = gross_realized - fee
        postings: list[Posting] = [
            Posting(self.cash_account, PostingSide.DEBIT, cash_received),
            Posting(f"asset:inventory:{instrument_id}", PostingSide.CREDIT, cost_basis),
        ]
        if fee.minor_units:
            postings.insert(1, Posting(f"expense:fees:{self.base_currency}", PostingSide.DEBIT, fee))
        if gross_realized.minor_units > 0:
            postings.append(
                Posting(
                    f"revenue:realized_gain:{self.base_currency}",
                    PostingSide.CREDIT,
                    gross_realized,
                )
            )
        elif gross_realized.minor_units < 0:
            postings.append(
                Posting(
                    f"expense:realized_loss:{self.base_currency}",
                    PostingSide.DEBIT,
                    Money(self.base_currency, -gross_realized.minor_units),
                )
            )
        entry = JournalEntry(
            entry_id=trade_id,
            occurred_at_ns=occurred_at_ns,
            description=f"SELL {instrument_id}",
            postings=tuple(postings),
        )
        inserted = self.ledger.post(entry)
        if not inserted:
            return TradeApplication(trade_id, False, Money.zero(self.base_currency), trade_id)
        remaining = current.quantity.value - quantity.value
        self._positions[instrument_id] = Position(
            instrument_id,
            Quantity.parse(remaining),
            current.average_cost if remaining else Decimal("0"),
            self.base_currency,
        )
        self._realized = self._realized + realized
        return TradeApplication(trade_id, True, realized, trade_id)

    def snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            base_currency=self.base_currency,
            cash=self.cash(),
            positions=tuple(self._positions[key] for key in sorted(self._positions)),
            realized_pnl=self._realized,
            ledger_sha256=self.ledger.sha256(),
        )
