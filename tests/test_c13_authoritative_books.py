from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from dataclasses import replace
import json
import subprocess
import sys

from marketos.canonical import canonical_json, canonical_sha256
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.ledger import JournalEntry, Posting, PostingSide
from marketos.money import Money, Price, Quantity
from marketos.orders import ExecutionMode, OrderIntent, OrderSide, OrderType, TimeInForce
from marketos.portfolio import PortfolioBook
from marketos.risk import RiskAction, RiskContext, RiskKernel, RiskLimits
from marketos.time import ClockQuality


class C13DurableLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"

    @staticmethod
    def entry(entry_id: str, amount: str = "100.00") -> JournalEntry:
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

    def test_reopen_reconstructs_entries_balances_and_hash(self) -> None:
        try:
            from marketos.authoritative_books import DurableLedger
        except ModuleNotFoundError as exc:
            self.fail(f"DurableLedger is not implemented: {exc}")

        original = self.entry("fund-1")
        with DurableLedger(self.path) as ledger:
            self.assertTrue(ledger.post(original))
            expected_sha = ledger.sha256()

        with DurableLedger(self.path) as reopened:
            self.assertEqual(reopened.entries(), (original,))
            self.assertEqual(
                reopened.balance("asset:cash:USD", "USD"),
                Money.from_decimal("USD", "100.00"),
            )
            self.assertEqual(reopened.sha256(), expected_sha)

    def test_identical_duplicate_is_idempotent_and_conflict_does_not_mutate(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = self.entry("fund-1", "100.00")
        conflict = self.entry("fund-1", "101.00")
        with DurableLedger(self.path) as ledger:
            self.assertTrue(ledger.post(first))
            self.assertFalse(ledger.post(first))
            with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
                ledger.post(conflict)
            self.assertEqual(len(ledger.entries()), 1)

    def test_batch_conflict_rolls_back_all_new_entries(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = self.entry("fund-1", "100.00")
        conflict = self.entry("fund-1", "101.00")
        with DurableLedger(self.path) as ledger:
            if not hasattr(ledger, "post_many"):
                self.fail("DurableLedger.post_many is not implemented")
            with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
                ledger.post_many((first, conflict))
            self.assertEqual(ledger.entries(), ())

    def test_reversal_is_persisted_and_reconstructible(self) -> None:
        from marketos.authoritative_books import DurableLedger

        original = self.entry("fund-1", "100.00")
        with DurableLedger(self.path) as ledger:
            ledger.post(original)
            if not hasattr(ledger, "reverse"):
                self.fail("DurableLedger.reverse is not implemented")
            reversal = ledger.reverse(
                "fund-1",
                reversal_id="reversal-1",
                occurred_at_ns=200,
            )
            self.assertEqual(reversal.reversal_of, "fund-1")
        with DurableLedger(self.path) as reopened:
            self.assertEqual(len(reopened.entries()), 2)
            self.assertEqual(
                reopened.balance("asset:cash:USD", "USD"),
                Money.zero("USD"),
            )

    def test_sqlite_update_and_delete_are_rejected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute(
                "UPDATE ledger_entries SET record_json = record_json WHERE entry_id = ?",
                ("fund-1",),
            )
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute(
                "DELETE FROM ledger_entries WHERE entry_id = ?",
                ("fund-1",),
            )

    def test_tampered_record_json_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_update")
        connection.execute(
            "UPDATE ledger_entries SET record_json = ? WHERE entry_id = ?",
            ("{}", "fund-1"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_tampered_row_metadata_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_update")
        connection.execute(
            "UPDATE ledger_entries SET occurred_at_ns = ? WHERE entry_id = ?",
            (999, "fund-1"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_tail_truncation_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_delete")
        connection.execute(
            "DELETE FROM ledger_entries WHERE entry_id = ?",
            ("fund-1",),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_coordinated_tail_truncation_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            DROP TRIGGER ledger_entries_no_delete;
            DROP TRIGGER ledger_heads_no_delete;
            """
        )
        connection.execute(
            "DELETE FROM ledger_entries WHERE entry_id = ?",
            ("fund-1",),
        )
        connection.execute("DELETE FROM ledger_heads WHERE head_sequence = 1")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_tampered_record_digest_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_update")
        connection.execute(
            "UPDATE ledger_entries SET record_sha256 = ? WHERE entry_id = ?",
            ("0" * 64, "fund-1"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_tampered_sequence_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
            ledger.post(self.entry("fund-2", "1.00"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_update")
        connection.execute(
            "UPDATE ledger_entries SET ledger_sequence = ? WHERE entry_id = ?",
            (3, "fund-2"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_tampered_previous_chain_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(self.entry("fund-1"))
            ledger.post(self.entry("fund-2", "1.00"))
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER ledger_entries_no_update")
        connection.execute(
            "UPDATE ledger_entries SET previous_sha256 = ? WHERE entry_id = ?",
            ("f" * 64, "fund-2"),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_sqlite_failure_rolls_back_batch(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            connection = sqlite3.connect(self.path)
            connection.executescript(
                """
                CREATE TRIGGER c13_fail_second_insert
                BEFORE INSERT ON ledger_entries
                WHEN NEW.entry_id = 'fund-2'
                BEGIN
                    SELECT RAISE(ABORT, 'C13_FAIL_BATCH');
                END;
                """
            )
            connection.commit()
            connection.close()
            with self.assertRaises(sqlite3.DatabaseError):
                ledger.post_many((self.entry("fund-1"), self.entry("fund-2", "1.00")))
            self.assertEqual(ledger.entries(), ())
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0], 0)

    def test_late_event_preserves_arrival_order(self) -> None:
        from marketos.authoritative_books import DurableLedger

        early = replace(self.entry("early"), occurred_at_ns=200)
        late = replace(self.entry("late", "1.00"), occurred_at_ns=100)
        with DurableLedger(self.path) as ledger:
            ledger.post(early)
            ledger.post(late)
            self.assertEqual(tuple(entry.entry_id for entry in ledger.entries()), ("early", "late"))
        with DurableLedger(self.path) as reopened:
            self.assertEqual(tuple(entry.entry_id for entry in reopened.entries()), ("early", "late"))

    def test_stale_writer_refreshes_inside_transaction(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = DurableLedger(self.path)
        second = DurableLedger(self.path)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertTrue(first.post(self.entry("fund-1")))
        self.assertTrue(second.post(self.entry("fund-2", "1.00")))
        self.assertTrue(second.verify())
        self.assertEqual(
            tuple(entry.entry_id for entry in second.entries()),
            ("fund-1", "fund-2"),
        )

    def test_stale_batch_writer_refreshes_inside_transaction(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = DurableLedger(self.path)
        second = DurableLedger(self.path)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertTrue(first.post(self.entry("fund-1")))
        self.assertEqual(
            second.post_many((self.entry("fund-2", "1.00"), self.entry("fund-3", "2.00"))),
            (True, True),
        )
        self.assertTrue(second.verify())
        self.assertEqual(
            tuple(entry.entry_id for entry in second.entries()),
            ("fund-1", "fund-2", "fund-3"),
        )

    def test_concurrent_reversal_is_rejected_by_current_ledger(self) -> None:
        from marketos.authoritative_books import DurableLedger

        first = DurableLedger(self.path)
        second = DurableLedger(self.path)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        original = self.entry("fund-1")
        self.assertTrue(first.post(original))
        first.reverse("fund-1", reversal_id="reverse-1", occurred_at_ns=200)
        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_ENTRY_ALREADY_REVERSED"):
            second.reverse("fund-1", reversal_id="reverse-2", occurred_at_ns=300)


class C13ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"

    def test_checkpoint_survives_reopen_and_reconciles(self) -> None:
        try:
            from marketos.authoritative_books import (
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 reconciliation is not implemented: {exc}")

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)

        with DurableLedger(self.path) as reopened:
            result = reconcile_book(reopened, snapshot)
            self.assertEqual(result.status, ReconciliationStatus.RECONCILED)
            self.assertEqual(result.reasons, ())

    def test_snapshot_divergence_is_reported(self) -> None:
        try:
            from marketos.authoritative_books import (
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 reconciliation is not implemented: {exc}")

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
            altered = replace(snapshot, cash=Money.from_decimal("USD", "99.00"))
            result = reconcile_book(ledger, altered)
            self.assertEqual(result.status, ReconciliationStatus.DIVERGENT)
            self.assertIn("BOOK_SNAPSHOT_MISMATCH", result.reasons)

    def test_new_ledger_entry_makes_checkpoint_stale(self) -> None:
        try:
            from marketos.authoritative_books import (
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 reconciliation is not implemented: {exc}")

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            snapshot = book.snapshot()
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
            ledger.post(
                JournalEntry(
                    entry_id="fund-2",
                    occurred_at_ns=300,
                    description="second fund",
                    postings=(
                        Posting(
                            "asset:cash:USD",
                            PostingSide.DEBIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                        Posting(
                            "equity:capital:USD",
                            PostingSide.CREDIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                    ),
                )
            )
            result = reconcile_book(ledger, snapshot)
            self.assertEqual(result.status, ReconciliationStatus.DIVERGENT)
            self.assertIn("CHECKPOINT_STALE", result.reasons)

    def test_unverified_snapshot_cannot_be_checkpointed(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            fake = replace(book.snapshot(), cash=Money.from_decimal("USD", "99.00"))
            with self.assertRaisesRegex(InvariantViolation, "INVALID_BOOK_CHECKPOINT_SOURCE"):
                ledger.checkpoint("fake", fake, captured_at_ns=200)

    def test_unreconstructed_bound_book_cannot_be_checkpointed(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            unreconstructed = PortfolioBook(base_currency="USD", ledger=ledger)
            with self.assertRaisesRegex(InvariantViolation, "INVALID_BOOK_CHECKPOINT_SOURCE"):
                ledger.checkpoint("unreconstructed", unreconstructed, captured_at_ns=200)

    def test_external_ledger_mutation_taints_authoritative_book(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            ledger.post(
                JournalEntry(
                    entry_id="fund-2",
                    occurred_at_ns=200,
                    description="external fund",
                    postings=(
                        Posting(
                            "asset:cash:USD",
                            PostingSide.DEBIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                        Posting(
                            "equity:capital:USD",
                            PostingSide.CREDIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                    ),
                )
            )
            with self.assertRaisesRegex(InvariantViolation, "BOOK_SOURCE_TAINTED"):
                ledger.checkpoint("tainted", book, captured_at_ns=300)

    def test_authoritative_book_requires_empty_ledger_for_new_state(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            ledger.post(
                JournalEntry(
                    entry_id="fund-1",
                    occurred_at_ns=100,
                    description="fund",
                    postings=(
                        Posting(
                            "asset:cash:USD",
                            PostingSide.DEBIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                        Posting(
                            "equity:capital:USD",
                            PostingSide.CREDIT,
                            Money.from_decimal("USD", "1.00"),
                        ),
                    ),
                )
            )
            with self.assertRaisesRegex(InvariantViolation, "BOOK_RECONSTRUCTION_REQUIRED"):
                ledger.authoritative_book(base_currency="USD")


class C13CheckpointReconstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"

    def test_current_head_checkpoint_restores_authoritative_book_after_reopen(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            expected = book.snapshot()
            self.assertTrue(ledger.checkpoint("checkpoint-1", book, captured_at_ns=200))

        with DurableLedger(self.path) as reopened:
            restored = reopened.authoritative_book(base_currency="USD")
            self.assertEqual(restored.snapshot(), expected)

    def test_existing_database_without_sidecar_fails_closed(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            self.assertEqual(ledger.entries(), ())
        self.path.with_name(self.path.name + ".anchor.json").unlink()

        with self.assertRaisesRegex(InvariantViolation, "JOURNAL_INTEGRITY_FAILURE"):
            DurableLedger(self.path)

    def test_legacy_sidecar_cannot_restore_checkpoint_state(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)

        anchor_path = self.path.with_name(self.path.name + ".anchor.json")
        current = json.loads(anchor_path.read_text(encoding="utf-8"))
        legacy_payload = {
            key: current[key]
            for key in (
                "head_sequence",
                "ledger_entry_count",
                "head_record_sha256",
                "head_ledger_sha256",
            )
        }
        legacy_payload["anchor_sha256"] = canonical_sha256(legacy_payload)
        anchor_path.write_text(canonical_json(legacy_payload), encoding="utf-8")

        with DurableLedger(self.path) as reopened:
            with self.assertRaisesRegex(
                InvariantViolation, "BOOK_CHECKPOINT_WITNESS_REQUIRED"
            ):
                reopened.authoritative_book(base_currency="USD")

    def test_checkpoint_row_rewrite_with_recomputed_digest_is_detected(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)

        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER book_checkpoints_no_update")
        record_json = str(
            connection.execute(
                "SELECT record_json FROM book_checkpoints WHERE checkpoint_id = ?",
                ("checkpoint-1",),
            ).fetchone()[0]
        )
        record = json.loads(record_json)
        record["snapshot"]["cash"]["minor_units"] = 9900
        rewritten_json = canonical_json(record)
        connection.execute(
            "UPDATE book_checkpoints SET record_json = ?, record_sha256 = ? "
            "WHERE checkpoint_id = ?",
            (rewritten_json, canonical_sha256(record), "checkpoint-1"),
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(
            InvariantViolation, "BOOK_CHECKPOINT_WITNESS_FAILURE"
        ):
            DurableLedger(self.path)

    def test_checkpoint_capture_cannot_precede_journal_entries(self) -> None:
        from marketos.authoritative_books import DurableLedger

        with DurableLedger(self.path) as ledger:
            book = ledger.authoritative_book(base_currency="USD")
            book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
            with self.assertRaisesRegex(
                InvariantViolation, "INVALID_BOOK_CHECKPOINT_TIME"
            ):
                ledger.checkpoint("checkpoint-1", book, captured_at_ns=99)


class C13RiskGateTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from marketos.authoritative_books import (
                C13RiskGate,
                DurableLedger,
                ReconciliationStatus,
                reconcile_book,
            )
        except ImportError as exc:
            self.fail(f"C13 risk gate is not implemented: {exc}")
        self.C13RiskGate = C13RiskGate
        self.DurableLedger = DurableLedger
        self.ReconciliationStatus = ReconciliationStatus
        self.reconcile_book = reconcile_book
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "authoritative-books.sqlite"
        self.ledger = DurableLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.book = self.ledger.authoritative_book(base_currency="USD")
        self.book.fund(
            "fund-1",
            Money.from_decimal("USD", "5000.00"),
            occurred_at_ns=100,
        )
        self.snapshot = self.book.snapshot()
        self.ledger.checkpoint("checkpoint-1", self.book, captured_at_ns=200)
        self.reconciled = reconcile_book(self.ledger, self.snapshot)
        self.kernel = RiskKernel(
            RiskLimits(
                currency="USD",
                allowed_instruments=frozenset({"AAPL"}),
                max_order_notional=Money.from_decimal("USD", "10000"),
                max_gross_notional=Money.from_decimal("USD", "20000"),
                max_position_quantity=Quantity.positive("100"),
                max_data_age_ns=100,
                max_clock_sync_age_ns=500,
                max_clock_error_ns=50,
                allow_short=False,
            )
        )

    def intent(self) -> OrderIntent:
        return OrderIntent(
            intent_id="intent-1",
            client_order_id="client-1",
            idempotency_key="idem-1",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Quantity.positive("10"),
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force=TimeInForce.IOC,
            created_at_ns=900,
            valid_from_ns=900,
            expires_at_ns=2_000,
            strategy_version="strategy@1",
            config_sha256="a" * 64,
            mode=ExecutionMode.PAPER,
        )

    def decision(self, *, cash: str = "5000"):
        return self.kernel.evaluate(
            self.intent(),
            RiskContext(
                now_ns=1_000,
                data_available_at_ns=950,
                portfolio_snapshot_sha256="b" * 64,
                ledger_head_sha256="c" * 64,
                market_view_sha256="d" * 64,
                clock_quality=ClockQuality("chrony", "NTP", 900, 20, 5, "SYNCED"),
                cash=Money.from_decimal("USD", cash),
                current_position=Quantity.parse("0"),
                current_gross_notional=Money.zero("USD"),
                mark_price=Price.parse("USD", "100", tick_size="0.01"),
                estimated_fee=Money.from_decimal("USD", "1"),
            ),
        )

    def test_reconciled_paper_allow_can_pass_gate(self) -> None:
        decision = self.decision()
        result = self.C13RiskGate().evaluate(
            decision,
            self.reconciled,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.ALLOW)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.live_trading_state, "HARD_LOCKED")

    def test_divergent_book_forces_no_trade(self) -> None:
        altered = self.snapshot.__class__(
            base_currency=self.snapshot.base_currency,
            cash=Money.from_decimal("USD", "4999.00"),
            positions=self.snapshot.positions,
            realized_pnl=self.snapshot.realized_pnl,
            ledger_sha256=self.snapshot.ledger_sha256,
        )
        divergent = self.reconcile_book(self.ledger, altered)
        result = self.C13RiskGate().evaluate(
            self.decision(),
            divergent,
            ExecutionMode.SHADOW,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("BOOKS_UNRECONCILED", result.reasons)

    def test_upstream_veto_and_unknown_mode_remain_no_trade(self) -> None:
        result = self.C13RiskGate().evaluate(
            self.decision(cash="0"),
            self.reconciled,
            "LIVE",
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("EXECUTION_MODE_NOT_ALLOWED", result.reasons)
        self.assertIn("UPSTREAM_NO_TRADE", result.reasons)

    def test_gate_lock_cannot_be_weakened_by_instance_override(self) -> None:
        decision = replace(self.decision(), live_trading_state="UNLOCKED")
        gate = self.C13RiskGate()
        gate.LIVE_TRADING_STATE = "UNLOCKED"
        result = gate.evaluate(decision, self.reconciled, ExecutionMode.PAPER)
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("LIVE_TRADING_LOCK_WEAKENED", result.reasons)

    def test_reconciliation_status_tampering_forces_no_trade(self) -> None:
        altered = replace(self.snapshot, cash=Money.from_decimal("USD", "4999.00"))
        divergent = self.reconcile_book(self.ledger, altered)
        forged = replace(divergent, status=self.ReconciliationStatus.RECONCILED)
        result = self.C13RiskGate().evaluate(
            self.decision(),
            forged,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("RECONCILIATION_INTEGRITY_FAILURE", result.reasons)

    def test_self_consistent_forged_reconciliation_cannot_pass_gate(self) -> None:
        from marketos.authoritative_books import BookReconciliation
        from marketos.canonical import canonical_sha256

        reasons = ()
        expected_sha256 = canonical_sha256(
            {
                "status": self.ReconciliationStatus.RECONCILED,
                "journal_sha256": self.ledger.sha256(),
                "book_sha256": self.snapshot.sha256(),
                "reasons": reasons,
            }
        )
        forged = BookReconciliation(
            status=self.ReconciliationStatus.RECONCILED,
            journal_sha256=self.ledger.sha256(),
            book_sha256=self.snapshot.sha256(),
            expected_sha256=expected_sha256,
            reasons=reasons,
        )
        result = self.C13RiskGate().evaluate(
            self.decision(),
            forged,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("RECONCILIATION_INTEGRITY_FAILURE", result.reasons)

    def test_reconciled_result_is_invalid_after_new_ledger_head(self) -> None:
        self.ledger.post(
            JournalEntry(
                entry_id="fund-2",
                occurred_at_ns=300,
                description="second fund",
                postings=(
                    Posting(
                        "asset:cash:USD",
                        PostingSide.DEBIT,
                        Money.from_decimal("USD", "1.00"),
                    ),
                    Posting(
                        "equity:capital:USD",
                        PostingSide.CREDIT,
                        Money.from_decimal("USD", "1.00"),
                    ),
                ),
            )
        )
        result = self.C13RiskGate().evaluate(
            self.decision(),
            self.reconciled,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("RECONCILIATION_INTEGRITY_FAILURE", result.reasons)

    def test_malformed_decision_returns_no_trade(self) -> None:
        result = self.C13RiskGate().evaluate(
            object(),
            self.reconciled,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("INVALID_RISK_DECISION", result.reasons)

    def test_malformed_reconciliation_returns_no_trade(self) -> None:
        result = self.C13RiskGate().evaluate(
            self.decision(),
            object(),
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)
        self.assertIn("INVALID_BOOK_RECONCILIATION", result.reasons)

    def test_noncanonical_decision_returns_no_trade(self) -> None:
        malformed = self.decision()
        object.__setattr__(malformed, "intent_id", object())
        result = self.C13RiskGate().evaluate(
            malformed,
            self.reconciled,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)

    def test_noncanonical_reconciliation_returns_no_trade(self) -> None:
        malformed = replace(self.reconciled, reasons=(object(),))
        result = self.C13RiskGate().evaluate(
            self.decision(),
            malformed,
            ExecutionMode.PAPER,
        )
        self.assertEqual(result.action, RiskAction.NO_TRADE)


class C13VerifierTests(unittest.TestCase):
    def test_c13_validator_reports_non_promotable_verified_slice(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "tools" / "verify_c13_contract.py"),
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
        self.assertTrue(all(payload["checks"].values()), payload)
        self.assertEqual(payload["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(payload["profitability_state"], "UNPROVEN")
        self.assertFalse(payload["promotion_allowed"])
        self.assertFalse(payload["phase_complete"])

    def test_c13_2_validator_reports_non_promotable_restart_slice(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "tools" / "verify_c13_checkpoint_reconstruction.py"),
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
        self.assertTrue(all(payload["checks"].values()), payload)
        self.assertEqual(payload["live_trading_state"], "HARD_LOCKED")
        self.assertEqual(payload["profitability_state"], "UNPROVEN")
        self.assertFalse(payload["promotion_allowed"])
        self.assertFalse(payload["phase_complete"])


if __name__ == "__main__":
    unittest.main()
