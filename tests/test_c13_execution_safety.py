from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
import json
import subprocess
import sys

from marketos.authoritative_books import DurableLedger
from marketos.canonical import canonical_sha256
from marketos.errors import DuplicateConflict, ExecutionStateChanged, InvariantViolation
from marketos.ledger import JournalEntry, Posting, PostingSide
from marketos.money import Money
from marketos.paper import MarketSnapshot, PaperBroker
from marketos.portfolio import PortfolioBook
from marketos.risk import RiskContext, RiskKernel, RiskLimits
from marketos.money import Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderState, OrderType, TimeInForce
from marketos.time import ClockQuality


class C13ExecutionTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "execution.sqlite"

    @staticmethod
    def funding_entry(entry_id: str, amount: str = "100.00") -> JournalEntry:
        money = Money.from_decimal("USD", amount)
        return JournalEntry(
            entry_id=entry_id,
            occurred_at_ns=100,
            description="fund",
            postings=(
                Posting("asset:cash:USD", PostingSide.DEBIT, money),
                Posting("equity:capital:USD", PostingSide.CREDIT, money),
            ),
        )

    def test_expected_head_is_checked_before_execution_body(self) -> None:
        first = DurableLedger(self.path)
        second = DurableLedger(self.path)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        book = first.authoritative_book(base_currency="USD")
        book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
        expected = second.sha256()
        self.assertNotEqual(first.sha256(), expected)

        with self.assertRaises(ExecutionStateChanged):
            with second.execution_transaction(expected):
                self.fail("a stale execution must not enter its commit body")

    def test_successful_execution_transaction_persists_book_and_checkpoint(self) -> None:
        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund(
                "fund-1",
                Money.from_decimal("USD", "100.00"),
                occurred_at_ns=100,
            )
            expected = ledger.sha256()
            with ledger.execution_transaction(expected):
                book.fund(
                    "fund-2",
                    Money.from_decimal("USD", "1.00"),
                    occurred_at_ns=200,
                )
                ledger.checkpoint("checkpoint-2", book, captured_at_ns=300)
            self.assertEqual(
                tuple(entry.entry_id for entry in ledger.entries()),
                ("fund-1", "fund-2"),
            )
            self.assertEqual(ledger.latest_checkpoint().checkpoint_id, "checkpoint-2")

        with DurableLedger(self.path) as reopened:
            self.assertEqual(
                tuple(entry.entry_id for entry in reopened.entries()),
                ("fund-1", "fund-2"),
            )
            self.assertEqual(reopened.latest_checkpoint().checkpoint_id, "checkpoint-2")

    def test_rollback_restores_ledger_book_checkpoint_and_anchor(self) -> None:
        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund(
                "fund-1",
                Money.from_decimal("USD", "100.00"),
                occurred_at_ns=100,
            )
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=150)
            entries_before = ledger.entries()
            snapshot_before = book.snapshot()
            checkpoints_before = (ledger.latest_checkpoint(),)
            anchor_before = ledger.anchor_path.read_bytes()

            with self.assertRaisesRegex(RuntimeError, "force rollback"):
                with ledger.execution_transaction(ledger.sha256()):
                    book.fund(
                        "fund-2",
                        Money.from_decimal("USD", "1.00"),
                        occurred_at_ns=200,
                    )
                    ledger.checkpoint("checkpoint-2", book, captured_at_ns=250)
                    raise RuntimeError("force rollback")

            self.assertEqual(ledger.entries(), entries_before)
            self.assertEqual(book.snapshot(), snapshot_before)
            self.assertEqual((ledger.latest_checkpoint(),), checkpoints_before)
            self.assertEqual(ledger.anchor_path.read_bytes(), anchor_before)

    def test_missing_anchor_on_nonempty_ledger_fails_closed(self) -> None:
        with DurableLedger(self.path) as ledger:
            ledger.post(self.funding_entry("fund-1"))
            ledger.anchor_path.unlink()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)


class C13EvidenceBindingTests(unittest.TestCase):
    @staticmethod
    def snapshot(instrument_id: str = "AAPL", bid: str = "99", ask: str = "100") -> MarketSnapshot:
        return MarketSnapshot(
            instrument_id=instrument_id,
            bid=Price.parse("USD", bid, tick_size="0.01"),
            ask=Price.parse("USD", ask, tick_size="0.01"),
            bid_size=Quantity.parse("100"),
            ask_size=Quantity.parse("100"),
            available_at_ns=950,
            source_event_id=f"quote-{instrument_id}",
        )

    @staticmethod
    def intent() -> OrderIntent:
        return OrderIntent(
            intent_id="evidence-intent",
            client_order_id="evidence-client",
            idempotency_key="evidence-idem",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Quantity.positive("1"),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=2_000,
            strategy_version="evidence@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )

    def test_market_snapshot_and_view_are_content_addressed(self) -> None:
        from marketos.paper import MarketView

        execution = self.snapshot()
        mark = self.snapshot("MSFT", "49", "50")
        view = MarketView(execution=execution, marks=(mark,))
        altered = replace(mark, bid=Price.parse("USD", "48", tick_size="0.01"))
        self.assertNotEqual(view.sha256(), MarketView(execution=execution, marks=(altered,)).sha256())

    def test_risk_context_source_hash_changes_decision_evidence(self) -> None:
        context = RiskContext(
            now_ns=1_000,
            data_available_at_ns=950,
            portfolio_snapshot_sha256="b" * 64,
            ledger_head_sha256="c" * 64,
            market_view_sha256="d" * 64,
            clock_quality=ClockQuality("chrony", "NTP", 900, 20, 5, "SYNCED"),
            cash=Money.from_decimal("USD", "1000"),
            current_position=Quantity.parse("0"),
            current_gross_notional=Money.zero("USD"),
            mark_price=Price.parse("USD", "100", tick_size="0.01"),
            estimated_fee=Money.from_decimal("USD", "1"),
        )
        limits = RiskLimits(
            currency="USD",
            allowed_instruments=frozenset({"AAPL"}),
            max_order_notional=Money.from_decimal("USD", "10000"),
            max_gross_notional=Money.from_decimal("USD", "20000"),
            max_position_quantity=Quantity.positive("100"),
            max_data_age_ns=100,
            max_clock_sync_age_ns=500,
            max_clock_error_ns=50,
        )
        first = RiskKernel(limits).evaluate(self.intent(), context)
        altered = RiskKernel(limits).evaluate(
            self.intent(),
            replace(context, market_view_sha256="f" * 64),
        )
        self.assertNotEqual(first.context_sha256, altered.context_sha256)

    def test_direct_paper_broker_submission_is_forbidden(self) -> None:
        book = PortfolioBook(base_currency="USD")
        broker = PaperBroker(
            portfolio=book,
            risk_kernel=RiskKernel(
                RiskLimits(
                    currency="USD",
                    allowed_instruments=frozenset({"AAPL"}),
                    max_order_notional=Money.from_decimal("USD", "10000"),
                    max_gross_notional=Money.from_decimal("USD", "20000"),
                    max_position_quantity=Quantity.positive("100"),
                    max_data_age_ns=100,
                    max_clock_sync_age_ns=500,
                    max_clock_error_ns=50,
                )
            ),
            fee_bps="0",
            slippage_bps="0",
        )
        with self.assertRaisesRegex(InvariantViolation, "PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN"):
            broker.submit(None, now_ns=0, clock_quality=None, books_reconciled=True)


class C13EnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        from marketos.execution_safety import C13PreTradeEnvelope

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "envelope.sqlite"
        self.ledger = DurableLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.book = self.ledger.authoritative_book(base_currency="USD")
        self.book.fund("fund", Money.from_decimal("USD", "1000"), occurred_at_ns=1)
        self.ledger.checkpoint("initial", self.book, captured_at_ns=2)
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
        self.broker = PaperBroker(
            portfolio=self.book,
            risk_kernel=RiskKernel(limits),
            fee_bps="10",
            slippage_bps="0",
        )
        self.broker.update_market(self.snapshot())
        self.clock = ClockQuality("chrony", "NTP", 900, 10, 0, "SYNCED")
        self.envelope = C13PreTradeEnvelope(
            broker=self.broker,
            book=self.book,
            ledger=self.ledger,
        )

    @staticmethod
    def snapshot(
        *,
        bid: str = "99",
        ask: str = "100",
        bid_size: str = "100",
        ask_size: str = "100",
        available_at_ns: int = 950,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            instrument_id="AAPL",
            bid=Price.parse("USD", bid, tick_size="0.01"),
            ask=Price.parse("USD", ask, tick_size="0.01"),
            bid_size=Quantity.parse(bid_size),
            ask_size=Quantity.parse(ask_size),
            available_at_ns=available_at_ns,
            source_event_id=f"quote-{available_at_ns}",
        )

    @staticmethod
    def intent(
        intent_id: str = "order-1",
        *,
        mode: ExecutionMode = ExecutionMode.PAPER,
        idempotency_key: str | None = None,
        quantity: str = "5",
    ) -> OrderIntent:
        return OrderIntent(
            intent_id=intent_id,
            client_order_id=f"client-{intent_id}",
            idempotency_key=idempotency_key or f"idem-{intent_id}",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Quantity.positive(quantity),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=2_000,
            strategy_version="strategy@1",
            config_sha256="a" * 64,
            mode=mode,
        )

    def test_paper_fill_and_checkpoint_use_one_envelope(self) -> None:
        report = self.envelope.submit(self.intent(), now_ns=1_000, clock_quality=self.clock)
        self.assertEqual(report.state, OrderState.FILLED)
        self.assertEqual(report.fills[0].quantity, Quantity.positive("5"))
        self.assertEqual(self.book.position("AAPL").quantity, Quantity.positive("5"))
        self.assertEqual(self.ledger.latest_checkpoint().checkpoint_id, "c13-1:idem-order-1")
        self.assertEqual(len(report.portfolio_snapshot_sha256), 64)
        self.assertTrue(report.c13_gate_sha256)
        self.assertEqual(
            report.report_sha256,
            canonical_sha256(report.canonical_dict(include_hash=False)),
        )

    def test_shadow_is_gated_but_never_mutates_book_or_ledger(self) -> None:
        entries_before = self.ledger.entries()
        report = self.envelope.submit(
            self.intent("shadow", mode=ExecutionMode.SHADOW),
            now_ns=1_000,
            clock_quality=self.clock,
        )
        self.assertEqual(report.state, OrderState.CANCELLED)
        self.assertIn("SHADOW_MODE_NO_EXECUTION", report.reasons)
        self.assertEqual(self.ledger.entries(), entries_before)
        self.assertEqual(self.book.position("AAPL").quantity, Quantity.parse("0"))

    def test_idempotency_is_stable_and_conflict_is_rejected(self) -> None:
        intent = self.intent()
        first = self.envelope.submit(intent, now_ns=1_000, clock_quality=self.clock)
        second = self.envelope.submit(intent, now_ns=1_000, clock_quality=self.clock)
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(first.fills, second.fills)
        conflict = self.intent("different", idempotency_key=intent.idempotency_key, quantity="1")
        with self.assertRaisesRegex(DuplicateConflict, "IDEMPOTENCY_KEY_CONFLICT"):
            self.envelope.submit(conflict, now_ns=1_000, clock_quality=self.clock)

    def test_forged_capability_cannot_commit(self) -> None:
        prepared = self.broker._prepare(
            self.intent(),
            now_ns=1_000,
            clock_quality=self.clock,
        )
        with self.assertRaisesRegex(InvariantViolation, "PAPER_BROKER_CAPABILITY_INVALID"):
            self.broker._commit_authorized(
                prepared,
                capability=object(),
                c13_gate=None,
            )

    def test_prepared_decision_and_gate_binding_tampering_fail_closed(self) -> None:
        from marketos.authoritative_books import C13RiskGate, reconcile_book

        prepared = self.broker._prepare(
            self.intent("tamper"),
            now_ns=1_000,
            clock_quality=self.clock,
        )
        reconciliation = reconcile_book(self.ledger, prepared.portfolio_snapshot)
        gate = C13RiskGate().evaluate(
            prepared.decision,
            reconciliation,
            ExecutionMode.PAPER,
            portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
            ledger_head_sha256=prepared.ledger_head_sha256,
            market_view_sha256=prepared.market_view_sha256,
        )
        tampered_prepared = replace(
            prepared,
            decision=replace(prepared.decision, reasons=("FORGED",)),
        )
        with self.assertRaisesRegex(InvariantViolation, "PREPARED_RISK_DECISION_INTEGRITY_FAILURE"):
            with self.ledger.execution_transaction(prepared.ledger_head_sha256):
                self.broker._commit_authorized(
                    tampered_prepared,
                    capability=self.envelope._capability,
                    c13_gate=gate,
                )
        tampered_gate = replace(gate, market_view_sha256="f" * 64)
        with self.assertRaisesRegex(InvariantViolation, "C13_GATE_INTEGRITY_FAILURE"):
            self.broker._commit_authorized(
                prepared,
                capability=self.envelope._capability,
                c13_gate=tampered_gate,
            )

    def test_failure_after_book_mutation_restores_everything(self) -> None:
        entries_before = self.ledger.entries()
        snapshot_before = self.book.snapshot()
        anchor_before = self.ledger.anchor_path.read_bytes()
        market_before = self.broker.market("AAPL")
        original_checkpoint = self.ledger.checkpoint

        def fail_checkpoint(*args, **kwargs):
            raise RuntimeError("forced checkpoint failure")

        self.ledger.checkpoint = fail_checkpoint
        self.addCleanup(setattr, self.ledger, "checkpoint", original_checkpoint)
        with self.assertRaisesRegex(RuntimeError, "forced checkpoint failure"):
            self.envelope.submit(self.intent(), now_ns=1_000, clock_quality=self.clock)
        self.assertEqual(self.ledger.entries(), entries_before)
        self.assertEqual(self.book.snapshot(), snapshot_before)
        self.assertEqual(self.ledger.anchor_path.read_bytes(), anchor_before)
        self.assertEqual(self.broker.market("AAPL"), market_before)
        self.assertEqual(self.broker._reports, {})

    def test_future_quote_and_missing_liquidity_are_fail_closed_reports(self) -> None:
        self.broker.update_market(self.snapshot(available_at_ns=1_100))
        future = self.envelope.submit(
            self.intent("future"),
            now_ns=1_000,
            clock_quality=self.clock,
        )
        self.assertEqual(future.state, OrderState.REJECTED)
        self.assertIn("FUTURE_DATA", future.reasons)

        self.broker.update_market(self.snapshot(available_at_ns=1_200, ask_size="0"))
        empty = self.envelope.submit(
            self.intent("empty"),
            now_ns=1_300,
            clock_quality=self.clock,
        )
        self.assertEqual(empty.state, OrderState.CANCELLED)
        self.assertIn("NO_VISIBLE_LIQUIDITY", empty.reasons)

    def test_divergent_checkpoint_and_sidecar_mismatch_are_vetoes(self) -> None:
        self.ledger.post(self.funding_entry("outside"))
        divergent = self.envelope.submit(
            self.intent("divergent"),
            now_ns=1_000,
            clock_quality=self.clock,
        )
        self.assertEqual(divergent.state, OrderState.REJECTED)
        self.assertIn("BOOKS_UNRECONCILED", divergent.reasons)

        self.ledger.anchor_path.write_text("{}", encoding="utf-8")
        mismatched = self.envelope.submit(
            self.intent("sidecar"),
            now_ns=1_000,
            clock_quality=self.clock,
        )
        self.assertEqual(mismatched.state, OrderState.REJECTED)
        self.assertIn("RECONCILIATION_INTEGRITY_FAILURE", mismatched.reasons)

    def test_expected_head_race_is_not_cached(self) -> None:
        from marketos.authoritative_books import C13RiskGate

        writer = DurableLedger(self.path)
        self.addCleanup(writer.close)
        original = C13RiskGate.evaluate
        raced = False

        def gate_then_write(gate_instance, *args, **kwargs):
            nonlocal raced
            result = original(gate_instance, *args, **kwargs)
            if not raced:
                raced = True
                writer.post(self.funding_entry("race"))
            return result

        C13RiskGate.evaluate = gate_then_write
        self.addCleanup(setattr, C13RiskGate, "evaluate", original)
        with self.assertRaisesRegex(ExecutionStateChanged, "EXECUTION_STATE_CHANGED"):
            self.envelope.submit(self.intent("race-order"), now_ns=1_000, clock_quality=self.clock)
        self.assertNotIn("idem-race-order", self.broker._reports)

    def test_unsupported_instrument_fails_closed_before_mutation(self) -> None:
        unsupported = replace(self.intent("unsupported"), instrument_id="MSFT")
        with self.assertRaisesRegex(InvariantViolation, "MISSING_MARKET_SNAPSHOT:MSFT"):
            self.envelope.submit(unsupported, now_ns=1_000, clock_quality=self.clock)

    @staticmethod
    def funding_entry(entry_id: str) -> JournalEntry:
        amount = Money.from_decimal("USD", "1")
        return JournalEntry(
            entry_id=entry_id,
            occurred_at_ns=400,
            description="external",
            postings=(
                Posting("asset:cash:USD", PostingSide.DEBIT, amount),
                Posting("equity:capital:USD", PostingSide.CREDIT, amount),
            ),
        )


class C13ExecutionSafetyValidatorTests(unittest.TestCase):
    def test_c13_1_validator_preserves_bounded_non_promotable_slice(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "tools" / "verify_c13_execution_safety.py"),
                "--root",
                str(root),
                "--json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["slice"], "C13-1")
        self.assertEqual(payload["status"], "VERIFIED_SLICE")
        self.assertEqual(
            set(payload["partial_requirements"]),
            {"AUD-RSK-001", "AUD-RSK-002", "AUD-RSK-004", "AUD-RSK-005", "AUD-RSK-009"},
        )
        self.assertFalse(payload["phase_complete"])
        self.assertFalse(payload["promotion_allowed"])
        self.assertEqual(payload["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(payload["profitability_state"], "UNPROVEN")
        self.assertTrue(payload["restart_reconstruction_blocked"])
        self.assertTrue(payload["simultaneous_db_witness_rewrite_excluded"])


if __name__ == "__main__":
    unittest.main()
