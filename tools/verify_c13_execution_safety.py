#!/usr/bin/env python3
"""Verify the bounded C13-1 pre-trade execution safety slice."""
from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import threading
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_checks(root: Path) -> tuple[dict[str, bool], list[str]]:
    sys.path.insert(0, str(root / "src"))
    from marketos.authoritative_books import C13RiskGate, DurableLedger, reconcile_book
    from marketos.errors import ExecutionStateChanged, InvariantViolation
    from marketos.execution_safety import C13PreTradeEnvelope
    from marketos.money import Money, Price, Quantity
    from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderState, OrderType, TimeInForce
    from marketos.paper import MarketSnapshot, PaperBroker
    from marketos.risk import RiskContext, RiskKernel, RiskLimits
    from marketos.replay import ReplayConfig, ReplayEngine
    from marketos.time import ClockQuality
    from marketos.ledger import JournalEntry, Posting, PostingSide

    def funding(entry_id: str) -> JournalEntry:
        amount = Money.from_decimal("USD", "1")
        return JournalEntry(
            entry_id=entry_id,
            occurred_at_ns=400,
            description="verification funding",
            postings=(
                Posting("asset:cash:USD", PostingSide.DEBIT, amount),
                Posting("equity:capital:USD", PostingSide.CREDIT, amount),
            ),
        )

    checks = {
        "paper_allow": False,
        "direct_submit_veto": False,
        "stale_head_veto": False,
        "sidecar_mismatch_veto": False,
        "reconstruction_veto": False,
        "capability_transaction_guard": False,
        "cache_finalized": False,
        "stale_mark_veto": False,
        "rollback_restored": False,
        "sidecar_write_failure_rollback": False,
        "partial_sidecar_replacement_rollback": False,
        "post_fill_refresh_failure_rollback": False,
        "writer_blocked_after_begin": False,
        "rejection_head_race_not_cached": False,
        "shadow_head_race_not_cached": False,
        "replay_path_independent": False,
    }
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="marketos-c13-1-verify-") as directory:
        path = Path(directory) / "books.sqlite"
        ledger = DurableLedger(path)
        try:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund", Money.from_decimal("USD", "1000"), occurred_at_ns=1)
            ledger.checkpoint("initial", book, captured_at_ns=2)
            limits = RiskLimits(
                currency="USD",
                allowed_instruments=frozenset({"AAPL"}),
                max_order_notional=Money.from_decimal("USD", "100000"),
                max_gross_notional=Money.from_decimal("USD", "100000"),
                max_position_quantity=Quantity.positive("1000"),
                max_data_age_ns=100,
                max_clock_sync_age_ns=500,
                max_clock_error_ns=50,
            )
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
                    950,
                    "verification-quote",
                )
            )
            envelope = C13PreTradeEnvelope(broker=broker, book=book, ledger=ledger)
            clock = ClockQuality("verify", "DETERMINISTIC", 900, 0, 0, "SYNCED")

            intent = OrderIntent(
                "verify-order",
                "verify-client",
                "verify-idem",
                "AAPL",
                OrderSide.BUY,
                Quantity.positive("1"),
                OrderType.MARKET,
                None,
                TimeInForce.IOC,
                900,
                900,
                2_000,
                "verify@1",
                "a" * 64,
                ExecutionMode.PAPER,
            )
            report = envelope.submit(intent, now_ns=1_000, clock_quality=clock)
            checks["paper_allow"] = (
                report.state is OrderState.FILLED
                and bool(report.fills)
                and ledger.latest_checkpoint() is not None
                and ledger.latest_checkpoint().checkpoint_id == "c13-1:verify-idem"
            )
            checks["cache_finalized"] = (
                "verify-idem" in broker._reports
                and broker.market("AAPL").ask_size == Quantity.parse("99")
            )

            entries_before = ledger.entries()
            snapshot_before = book.snapshot()
            checkpoints_before = tuple(ledger._checkpoints)
            anchor_before = ledger.anchor_path.read_bytes()
            market_before = broker.market("AAPL")
            reports_before = dict(broker._reports)
            original_refresh = ledger._refresh_checkpoints
            refresh_calls = 0

            def fail_after_fill_refresh():
                nonlocal refresh_calls
                if ledger._execution_transaction_active:
                    refresh_calls += 1
                    raise RuntimeError("verification post-fill refresh failure")
                return original_refresh()

            ledger._refresh_checkpoints = fail_after_fill_refresh
            try:
                try:
                    envelope.submit(
                        replace(
                            intent,
                            intent_id="post-fill-refresh-order",
                            idempotency_key="post-fill-refresh-idem",
                        ),
                        now_ns=1_000,
                        clock_quality=clock,
                    )
                except RuntimeError as exc:
                    checks["post_fill_refresh_failure_rollback"] = (
                        str(exc) == "verification post-fill refresh failure"
                        and refresh_calls == 1
                        and ledger.entries() == entries_before
                        and book.snapshot() == snapshot_before
                        and tuple(ledger._checkpoints) == checkpoints_before
                        and ledger.anchor_path.read_bytes() == anchor_before
                        and broker.market("AAPL") == market_before
                        and broker._reports == reports_before
                    )
            finally:
                ledger._refresh_checkpoints = original_refresh

            original_replace = ledger._replace_anchor_bytes
            replacement_calls = 0

            def partial_replace(content: bytes):
                nonlocal replacement_calls
                replacement_calls += 1
                if replacement_calls == 1:
                    ledger.anchor_path.write_bytes(b'{"partial":')
                    raise RuntimeError("verification partial sidecar replacement")
                return original_replace(content)

            ledger._replace_anchor_bytes = partial_replace
            try:
                try:
                    envelope.submit(
                        replace(
                            intent,
                            intent_id="partial-sidecar-order",
                            idempotency_key="partial-sidecar-idem",
                        ),
                        now_ns=1_000,
                        clock_quality=clock,
                    )
                except RuntimeError as exc:
                    checks["partial_sidecar_replacement_rollback"] = (
                        str(exc) == "verification partial sidecar replacement"
                        and replacement_calls >= 2
                        and ledger.entries() == entries_before
                        and book.snapshot() == snapshot_before
                        and ledger.anchor_path.read_bytes() == anchor_before
                        and broker.market("AAPL") == market_before
                        and broker._reports == reports_before
                    )
            finally:
                ledger._replace_anchor_bytes = original_replace

            guarded_intent = replace(
                intent,
                intent_id="guarded-order",
                idempotency_key="guarded-idem",
            )
            prepared = broker._prepare(
                guarded_intent,
                now_ns=1_000,
                clock_quality=clock,
            )
            reconciliation = reconcile_book(ledger, prepared.portfolio_snapshot)
            guard_gate = C13RiskGate().evaluate(
                prepared.decision,
                reconciliation,
                ExecutionMode.PAPER,
                portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                ledger_head_sha256=prepared.ledger_head_sha256,
                market_view_sha256=prepared.market_view_sha256,
            )
            try:
                broker._commit_authorized(
                    prepared,
                    capability=envelope._capability,
                    transaction_owner=envelope._transaction_owner,
                    c13_gate=guard_gate,
                )
            except InvariantViolation as exc:
                checks["capability_transaction_guard"] = str(exc) == "EXECUTION_TRANSACTION_REQUIRED"

            stale_context = RiskContext(
                now_ns=1_000,
                data_available_at_ns=950,
                portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                ledger_head_sha256=prepared.ledger_head_sha256,
                market_view_sha256=prepared.market_view_sha256,
                clock_quality=clock,
                cash=prepared.portfolio_snapshot.cash,
                current_position=Quantity.parse("0"),
                current_gross_notional=Money.zero("USD"),
                mark_price=Price.parse("USD", "100", tick_size="0.01"),
                estimated_fee=Money.zero("USD"),
                market_evidence_available_at_ns=(("AAPL", 950), ("MSFT", 0)),
            )
            checks["stale_mark_veto"] = "STALE_DATA" in RiskKernel(limits).evaluate(
                guarded_intent,
                stale_context,
            ).reasons

            entries_before = ledger.entries()
            snapshot_before = book.snapshot()
            anchor_before = ledger.anchor_path.read_bytes()
            try:
                with ledger.execution_transaction(
                    ledger.sha256(),
                    owner=envelope._transaction_owner,
                ):
                    book.fund("rollback", Money.from_decimal("USD", "1"), occurred_at_ns=500)
                    raise RuntimeError("verification rollback")
            except RuntimeError:
                checks["rollback_restored"] = (
                    ledger.entries() == entries_before
                    and book.snapshot() == snapshot_before
                    and ledger.anchor_path.read_bytes() == anchor_before
                )

            original_write_anchor = ledger._write_anchor
            try:
                def fail_write_anchor(candidate):
                    raise RuntimeError("verification sidecar write failure")

                ledger._write_anchor = fail_write_anchor
                try:
                    with ledger.execution_transaction(
                        ledger.sha256(),
                        owner=envelope._transaction_owner,
                    ):
                        pass
                except RuntimeError:
                    checks["sidecar_write_failure_rollback"] = (
                        ledger.entries() == entries_before
                        and ledger.anchor_path.read_bytes() == anchor_before
                    )
            finally:
                ledger._write_anchor = original_write_anchor

            writer_path = Path(directory) / "writer-race.sqlite"
            locked_ledger = DurableLedger(writer_path)
            locked_owner = object()
            locked_ledger._bind_execution_owner(locked_owner)
            writer_started = threading.Event()
            writer_go = threading.Event()
            writer_done = threading.Event()
            writer_errors: list[BaseException] = []

            def blocked_writer() -> None:
                writer = DurableLedger(writer_path)
                writer_started.set()
                try:
                    writer_go.wait(2)
                    writer.post(funding("writer-after-begin"))
                except BaseException as exc:
                    writer_errors.append(exc)
                finally:
                    writer.close()
                    writer_done.set()

            writer_thread = threading.Thread(target=blocked_writer, daemon=True)
            try:
                with locked_ledger.execution_transaction(
                    locked_ledger.sha256(),
                    owner=locked_owner,
                ):
                    writer_thread.start()
                    started = writer_started.wait(2)
                    writer_go.set()
                    blocked = started and not writer_done.wait(0.1)
                writer_thread.join(2)
                checks["writer_blocked_after_begin"] = (
                    blocked and writer_done.is_set() and not writer_errors
                )
            finally:
                if writer_thread.is_alive():
                    writer_thread.join(2)
                locked_ledger.close()

            def race_report(mode, quantity: str, run_id: str, entry_id: str):
                race_path = Path(directory) / f"{run_id}.sqlite"
                race_ledger = DurableLedger(race_path)
                race_book = race_ledger.authoritative_book(base_currency="USD")
                race_book.fund("fund", Money.from_decimal("USD", "1000"), occurred_at_ns=1)
                race_ledger.checkpoint("initial", race_book, captured_at_ns=2)
                race_broker = PaperBroker(
                    portfolio=race_book,
                    risk_kernel=RiskKernel(limits),
                    fee_bps="10",
                    slippage_bps="0",
                )
                race_broker.update_market(
                    MarketSnapshot(
                        "AAPL",
                        Price.parse("USD", "99", tick_size="0.01"),
                        Price.parse("USD", "100", tick_size="0.01"),
                        Quantity.parse("100"),
                        Quantity.parse("100"),
                        950,
                        f"{run_id}-quote",
                    )
                )
                race_envelope = C13PreTradeEnvelope(
                    broker=race_broker,
                    book=race_book,
                    ledger=race_ledger,
                )
                race_writer = DurableLedger(race_path)
                original_evaluate = C13RiskGate.evaluate
                raced = False

                def gate_then_write(gate_instance, *args, **kwargs):
                    nonlocal raced
                    result = original_evaluate(gate_instance, *args, **kwargs)
                    if not raced:
                        raced = True
                        race_writer.post(funding(entry_id))
                    return result

                C13RiskGate.evaluate = gate_then_write
                try:
                    report = race_envelope.submit(
                        replace(
                            intent,
                            intent_id=f"{run_id}-order",
                            idempotency_key=f"{run_id}-idem",
                            mode=mode,
                            quantity=Quantity.positive(quantity),
                        ),
                        now_ns=1_000,
                        clock_quality=clock,
                    )
                    return report, race_broker
                finally:
                    C13RiskGate.evaluate = original_evaluate
                    race_writer.close()
                    race_ledger.close()

            rejection_report, rejection_broker = race_report(
                ExecutionMode.PAPER,
                "1000000",
                "rejection-race",
                "rejection-race-writer",
            )
            checks["rejection_head_race_not_cached"] = (
                rejection_report.state is OrderState.REJECTED
                and "EXECUTION_STATE_CHANGED" in rejection_report.reasons
                and "rejection-race-idem" not in rejection_broker._reports
            )
            shadow_report, shadow_broker = race_report(
                ExecutionMode.SHADOW,
                "1",
                "shadow-race",
                "shadow-race-writer",
            )
            checks["shadow_head_race_not_cached"] = (
                shadow_report.state is OrderState.REJECTED
                and "EXECUTION_STATE_CHANGED" in shadow_report.reasons
                and "shadow-race-idem" not in shadow_broker._reports
            )

            scenario_path = root / "examples" / "paper_scenario.jsonl"
            if scenario_path.is_file():
                from marketos.config import load_events_jsonl

                scenario = load_events_jsonl(scenario_path)
                replay_config = ReplayConfig(
                    "c13-1-validator",
                    "USD",
                    Money.from_decimal("USD", "1000"),
                    Decimal("10"),
                    Decimal("0"),
                )
                first = ReplayEngine(config=replay_config, risk_limits=limits).run(scenario)
                second = ReplayEngine(config=replay_config, risk_limits=limits).run(reversed(scenario))
                checks["replay_path_independent"] = first.fingerprint == second.fingerprint

            try:
                broker.submit(None, now_ns=1_000, clock_quality=clock)
            except InvariantViolation as exc:
                checks["direct_submit_veto"] = str(exc) == "PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN"

            expected = ledger.sha256()
            writer = DurableLedger(path)
            try:
                writer.post(funding("outside"))
            finally:
                writer.close()
            try:
                with ledger.execution_transaction(expected, owner=envelope._transaction_owner):
                    pass
            except ExecutionStateChanged as exc:
                checks["stale_head_veto"] = str(exc) == "EXECUTION_STATE_CHANGED"

            ledger.anchor_path.write_text("{}", encoding="utf-8")
            sidecar_intent = replace(intent, intent_id="sidecar-order", idempotency_key="sidecar-idem")
            sidecar_report = envelope.submit(
                sidecar_intent,
                now_ns=1_000,
                clock_quality=clock,
            )
            checks["sidecar_mismatch_veto"] = (
                sidecar_report.state is OrderState.REJECTED
                and "RECONCILIATION_INTEGRITY_FAILURE" in sidecar_report.reasons
            )
        finally:
            ledger.close()

        reconstruction_path = Path(directory) / "reconstruction.sqlite"
        with DurableLedger(reconstruction_path) as nonempty:
            nonempty.post(funding("nonempty"))
            try:
                nonempty.authoritative_book(base_currency="USD")
            except InvariantViolation as exc:
                checks["reconstruction_veto"] = str(exc) == "BOOK_RECONSTRUCTION_REQUIRED"

    errors.extend(f"RUNTIME_CHECK_FAILED:{name}" for name, value in checks.items() if not value)
    return checks, errors


def verify_c13_execution_safety(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    required = [
        "src/marketos/execution_safety.py",
        "src/marketos/paper.py",
        "src/marketos/risk.py",
        "tests/test_c13_execution_safety.py",
        "tools/verify_c13_execution_safety.py",
        "docs/implementation/C13_1_PRE_TRADE_EXECUTION_SAFETY.md",
        "planning/phases/C13/C13_1_EXECUTION_CONTRACT.md",
        "planning/phases/C13/C13_1_DECISIONS.json",
        "planning/phases/C13/C13_1_REQUIREMENT_CLOSURE.json",
        "authority/CURRENT_STATE.json",
    ]
    checks = {"required_artifacts": all((root / path).is_file() for path in required)}
    errors.extend(f"MISSING_ARTIFACT:{path}" for path in required if not (root / path).is_file())

    decisions: dict[str, Any] = {}
    closure: dict[str, Any] = {}
    state: dict[str, Any] = {}
    contract = ""
    implementation = ""
    try:
        decisions = _load(root / "planning/phases/C13/C13_1_DECISIONS.json")
        closure = _load(root / "planning/phases/C13/C13_1_REQUIREMENT_CLOSURE.json")
        state = _load(root / "authority/CURRENT_STATE.json")
        contract = (root / "planning/phases/C13/C13_1_EXECUTION_CONTRACT.md").read_text(encoding="utf-8")
        implementation = (root / "docs/implementation/C13_1_PRE_TRADE_EXECUTION_SAFETY.md").read_text(encoding="utf-8")
    except Exception as exc:
        errors.append(f"INVALID_C13_1_ARTIFACT:{exc}")

    requirement_ids = [item.get("id") for item in closure.get("requirements", []) if isinstance(item, dict)]
    checks["decision_boundary"] = (
        decisions.get("phase") == "C13"
        and decisions.get("slice") == "C13-1"
        and decisions.get("status") == "VERIFIED_SLICE"
        and decisions.get("verification", {}).get("phase_complete") is False
        and decisions.get("verification", {}).get("promotion_allowed") is False
    )
    checks["partial_requirement_boundary"] = (
        set(requirement_ids)
        == {"AUD-RSK-001", "AUD-RSK-002", "AUD-RSK-004", "AUD-RSK-005", "AUD-RSK-009"}
        and closure.get("status") == "VERIFIED_SLICE"
        and closure.get("hard_boundary", {}).get("phase_complete") is False
        and all(
            item.get("state") == "PARTIAL_VERIFIED_C13_1"
            for item in closure.get("requirements", [])
            if isinstance(item, dict)
        )
    )
    checks["authority_locks"] = (
        state.get("live_trading_state") == "HARD_LOCKED"
        and state.get("profitability_state") == "UNPROVEN"
        and state.get("software_implementation_complete") is False
    )
    checks["reconstruction_scope"] = (
        "BOOK_RECONSTRUCTION_REQUIRED" in contract
        and "no restart reconstruction" in contract.lower()
    )
    checks["simultaneous_witness_scope"] = (
        "simultaneous" in contract.lower()
        and "witness" in contract.lower()
        and "out of scope" in contract.lower()
    )
    checks["paper_shadow_only"] = (
        "PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN" in implementation
        and "PAPER" in implementation
        and "SHADOW" in implementation
        and "HARD_LOCKED" in implementation
    )
    runtime_checks, runtime_errors = _runtime_checks(root) if checks["required_artifacts"] else ({}, [])
    checks.update(runtime_checks)
    errors.extend(runtime_errors)

    return {
        "ok": not errors and all(checks.values()),
        "errors": errors,
        "checks": checks,
        "phase": "C13",
        "slice": "C13-1",
        "status": "VERIFIED_SLICE",
        "partial_requirements": requirement_ids,
        "phase_complete": False,
        "promotion_allowed": False,
        "live_trading_state": state.get("live_trading_state", "HARD_LOCKED"),
        "profitability_state": state.get("profitability_state", "UNPROVEN"),
        "restart_reconstruction_blocked": checks.get("reconstruction_scope", False),
        "simultaneous_db_witness_rewrite_excluded": checks.get("simultaneous_witness_scope", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_c13_execution_safety(Path(args.root))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
