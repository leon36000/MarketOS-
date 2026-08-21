#!/usr/bin/env python3
"""Fresh acceptance checks for the MARKET-OS foundation slice."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from marketos.canonical import canonical_sha256
from marketos.authoritative_books import DurableLedger
from marketos.config import load_events_jsonl, load_risk_limits
from marketos.errors import InvariantViolation
from marketos.events import EventEnvelope, EventKind, sort_events
from marketos.ledger import JournalEntry, Ledger, Posting, PostingSide
from marketos.money import Money, Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
from marketos.execution_safety import C13PreTradeEnvelope
from marketos.paper import MarketSnapshot, PaperBroker
from marketos.replay import ReplayConfig, ReplayEngine
from marketos.risk import RiskAction, RiskContext, RiskKernel
from marketos.store import SQLiteEventStore
from marketos.time import ClockQuality, EventTime


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def _check(name: str, function: Callable[[], str]) -> Check:
    try:
        return Check(name, True, function())
    except Exception as exc:
        return Check(name, False, f"{type(exc).__name__}:{exc}")


def _event(event_id: str, sequence: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        kind=EventKind.SYSTEM,
        time=EventTime(10, 20, 20, 5),
        source_id="foundation-verifier",
        source_priority=0,
        source_sequence=sequence,
        schema_version="1",
        payload={"sequence": sequence},
    )


def verify() -> dict[str, object]:
    limits = load_risk_limits(ROOT / "config/paper-risk.json")
    scenario = load_events_jsonl(ROOT / "examples/paper_scenario.jsonl")

    def canonical_check() -> str:
        left = canonical_sha256({"b": 2, "a": Decimal("1.00")})
        right = canonical_sha256({"a": Decimal("1"), "b": 2})
        if left != right:
            raise AssertionError("canonical hash changed with map order")
        try:
            canonical_sha256({"float": 1.5})
        except InvariantViolation:
            return left
        raise AssertionError("float was accepted")

    def money_check() -> str:
        total = Money.from_decimal("USD", "0.10") + Money.from_decimal("USD", "0.20")
        if total.to_decimal() != Decimal("0.30"):
            raise AssertionError(total)
        return str(total.minor_units)

    def event_order_check() -> str:
        ordered = sort_events([_event("second", 2), _event("first", 1)])
        if [item.event_id for item in ordered] != ["first", "second"]:
            raise AssertionError("event order mismatch")
        return ",".join(item.event_id for item in ordered)

    def store_check() -> str:
        with tempfile.TemporaryDirectory(prefix="marketos-foundation-store-") as temp_dir:
            path = Path(temp_dir) / "events.sqlite3"
            with SQLiteEventStore(path) as store:
                store.append_many((_event("one", 1), _event("two", 2)))
                if not store.verify_chain().ok:
                    raise AssertionError("fresh chain failed")
            connection = sqlite3.connect(path)
            connection.execute("UPDATE events SET event_json = '{}' WHERE event_id = 'one'")
            connection.commit()
            connection.close()
            with SQLiteEventStore(path) as store:
                if store.verify_chain().ok:
                    raise AssertionError("tamper was not detected")
            return "tamper-detected"

    def ledger_check() -> str:
        ledger = Ledger()
        amount = Money.from_decimal("USD", "100")
        ledger.post(
            JournalEntry(
                "fund",
                1,
                "fund",
                (
                    Posting("asset:cash:USD", PostingSide.DEBIT, amount),
                    Posting("equity:capital:USD", PostingSide.CREDIT, amount),
                ),
            )
        )
        ledger.reverse("fund", reversal_id="reverse", occurred_at_ns=2)
        if ledger.balance("asset:cash:USD", "USD") != Money.zero("USD"):
            raise AssertionError("reversal did not net")
        return ledger.sha256()

    def risk_check() -> str:
        kernel = RiskKernel(limits)
        intent = OrderIntent(
            intent_id="verify-intent",
            client_order_id="verify-client",
            idempotency_key="verify-idem",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Quantity.positive("1"),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=90,
            valid_from_ns=90,
            expires_at_ns=200,
            strategy_version="verify@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )
        context = RiskContext(
            now_ns=100,
            data_available_at_ns=99,
            portfolio_snapshot_sha256="b" * 64,
            ledger_head_sha256="c" * 64,
            market_view_sha256="d" * 64,
            clock_quality=ClockQuality("verify", "DETERMINISTIC", 100, 0, 0, "SYNCED"),
            cash=Money.from_decimal("USD", "1000"),
            current_position=Quantity.parse("0"),
            current_gross_notional=Money.zero("USD"),
            mark_price=Price.parse("USD", "100", tick_size="0.01"),
            estimated_fee=Money.zero("USD"),
        )
        allowed = kernel.evaluate(intent, context)
        denied = kernel.evaluate(
            intent,
            RiskContext(
                now_ns=100,
                data_available_at_ns=101,
                portfolio_snapshot_sha256=context.portfolio_snapshot_sha256,
                ledger_head_sha256=context.ledger_head_sha256,
                market_view_sha256=context.market_view_sha256,
                clock_quality=context.clock_quality,
                cash=context.cash,
                current_position=context.current_position,
                current_gross_notional=context.current_gross_notional,
                mark_price=context.mark_price,
                estimated_fee=context.estimated_fee,
            ),
        )
        if allowed.action is not RiskAction.ALLOW or denied.action is not RiskAction.NO_TRADE:
            raise AssertionError("risk gate mismatch")
        return allowed.decision_sha256

    def paper_check() -> str:
        with tempfile.TemporaryDirectory(prefix="marketos-foundation-paper-") as temp_dir:
            ledger = DurableLedger(Path(temp_dir) / "paper.sqlite")
            try:
                book = ledger.authoritative_book(base_currency="USD")
                book.fund("fund", Money.from_decimal("USD", "1000"), occurred_at_ns=1)
                ledger.checkpoint("initial", book, captured_at_ns=2)
                broker = PaperBroker(
                    portfolio=book,
                    risk_kernel=RiskKernel(limits),
                    fee_bps="10",
                    slippage_bps="0",
                )
                broker.update_market(
                    MarketSnapshot(
                        "AAPL",
                        Price.parse("USD", "99", tick_size="0.01"),
                        Price.parse("USD", "100", tick_size="0.01"),
                        Quantity.parse("100"),
                        Quantity.parse("100"),
                        100,
                        "quote",
                    )
                )
                envelope = C13PreTradeEnvelope(
                    broker=broker,
                    book=book,
                    ledger=ledger,
                )
                intent = OrderIntent(
                    "paper-buy",
                    "paper-client",
                    "paper-idem",
                    "AAPL",
                    OrderSide.BUY,
                    Quantity.positive("1"),
                    OrderType.MARKET,
                    None,
                    TimeInForce.IOC,
                    90,
                    90,
                    200,
                    "verify@1",
                    "a" * 64,
                    ExecutionMode.PAPER,
                )
                report = envelope.submit(
                    intent,
                    now_ns=110,
                    clock_quality=ClockQuality("verify", "DETERMINISTIC", 110, 0, 0, "SYNCED"),
                )
                if not report.fills or book.position("AAPL").quantity != Quantity.positive("1"):
                    raise AssertionError("paper fill missing")
                return report.report_sha256
            finally:
                ledger.close()

    def replay_check() -> str:
        config = ReplayConfig(
            "acceptance",
            limits.currency,
            Money.from_decimal(limits.currency, "1000"),
            Decimal("10"),
            Decimal("0"),
        )
        first = ReplayEngine(config=config, risk_limits=limits).run(scenario)
        second = ReplayEngine(config=config, risk_limits=limits).run(reversed(scenario))
        if first.fingerprint != second.fingerprint:
            raise AssertionError("replay fingerprint mismatch")
        if first.portfolio.cash.to_decimal() != Decimal("1048.95"):
            raise AssertionError("unexpected replay cash")
        return first.fingerprint

    def lock_check() -> str:
        try:
            ExecutionMode("LIVE")
        except ValueError:
            return "HARD_LOCKED"
        raise AssertionError("live mode exists")

    checks = [
        _check("canonical-evidence", canonical_check),
        _check("exact-money", money_check),
        _check("event-order", event_order_check),
        _check("hash-chain-tamper", store_check),
        _check("double-entry-reversal", ledger_check),
        _check("risk-allow-and-veto", risk_check),
        _check("paper-execution", paper_check),
        _check("deterministic-replay", replay_check),
        _check("live-route-absent", lock_check),
    ]
    return {
        "ok": all(check.ok for check in checks),
        "check_count": len(checks),
        "checks": [check.as_dict() for check in checks],
        "live_trading": "HARD_LOCKED",
        "profitability": "UNPROVEN",
        "software_scope": "FOUNDATION_AND_PAPER_CORE_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for check in report["checks"]:
            print(f"- {check['name']}: {'PASS' if check['ok'] else 'FAIL'} — {check['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
