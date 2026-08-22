"""Command-line interface for the non-live MARKET-OS foundation."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any

from .config import load_events_jsonl, load_risk_limits
from .errors import DomainError, InvariantViolation
from .money import Money
from .replay import ReplayConfig, ReplayEngine
from .store import SQLiteEventStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marketos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="Validate a paper risk policy")
    validate.add_argument("--risk", required=True)

    replay = subparsers.add_parser("replay", help="Run deterministic paper replay")
    replay.add_argument("--input", required=True)
    replay.add_argument("--risk", required=True)
    replay.add_argument("--db")
    replay.add_argument("--run-id", default="cli-replay")
    replay.add_argument("--initial-cash", default="100000.00")
    replay.add_argument("--fee-bps", default="10")
    replay.add_argument("--slippage-bps", default="0")
    replay.add_argument("--max-events", type=int)
    replay.add_argument("--knowledge-cutoff-ns", type=int)
    replay.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    return parser


def _money_dict(value: Money) -> dict[str, Any]:
    return {
        "currency": value.currency,
        "minor_units": value.minor_units,
        "decimal": format(value.to_decimal(), "f"),
    }


def _validate_config(args: argparse.Namespace) -> dict[str, Any]:
    limits = load_risk_limits(args.risk)
    return {
        "ok": True,
        "risk_limits_sha256": limits.sha256(),
        "allowed_instruments": sorted(limits.allowed_instruments),
        "live_trading": "HARD_LOCKED",
        "profitability": "UNPROVEN",
    }


def _replay(args: argparse.Namespace) -> dict[str, Any]:
    if args.live:
        raise InvariantViolation("LIVE_TRADING_HARD_LOCKED")
    limits = load_risk_limits(args.risk)
    events = load_events_jsonl(args.input)
    initial_cash = Money.from_decimal(limits.currency, args.initial_cash)
    config = ReplayConfig(
        run_id=args.run_id,
        base_currency=limits.currency,
        initial_cash=initial_cash,
        fee_bps=Decimal(args.fee_bps),
        slippage_bps=Decimal(args.slippage_bps),
        max_events=args.max_events,
        knowledge_cutoff_ns=args.knowledge_cutoff_ns,
    )
    if args.db:
        with SQLiteEventStore(Path(args.db)) as store:
            result = ReplayEngine(config=config, risk_limits=limits, store=store).run(events)
            event_chain = store.verify_chain()
            evidence_chain = store.verify_evidence_chain()
    else:
        result = ReplayEngine(config=config, risk_limits=limits).run(events)
        event_chain = evidence_chain = None
    return {
        "ok": True,
        "status": result.status.value,
        "fingerprint": result.fingerprint,
        "events_processed": result.events_processed,
        "cash": _money_dict(result.portfolio.cash),
        "realized_pnl": _money_dict(result.portfolio.realized_pnl),
        "positions": [
            {
                "instrument_id": position.instrument_id,
                "quantity": format(position.quantity.value, "f"),
                "average_cost": format(position.average_cost, "f"),
                "currency": position.currency,
            }
            for position in result.portfolio.positions
        ],
        "reports": [
            {
                "intent_id": report.intent_id,
                "state": report.state.value,
                "reasons": list(report.reasons),
                "fill_count": len(report.fills),
                "report_sha256": report.report_sha256,
            }
            for report in result.reports
        ],
        "event_chain_ok": None if event_chain is None else event_chain.ok,
        "evidence_chain_ok": None if evidence_chain is None else evidence_chain.ok,
        "live_trading": "HARD_LOCKED",
        "profitability": "UNPROVEN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        payload = _validate_config(args) if args.command == "validate-config" else _replay(args)
    except (DomainError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "live_trading": "HARD_LOCKED",
                    "profitability": "UNPROVEN",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0
