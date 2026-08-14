from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import UUID

from marketos.datafabric import RawEvidenceStore
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.execution_evidence import (
    EvidenceOrigin,
    ExecutionContext,
    ExecutionEvidenceLedger,
    ExecutionOutcome,
    Marketability,
)
from marketos.money import Money, Price, Quantity
from marketos.orders import OrderSide, OrderType


VENUE_ID = UUID("00000000-0000-0000-0000-000000011010")


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-execution-evidence-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.raw = RawEvidenceStore(self.temp / "raw")
        self.addCleanup(self.raw.close)
        self.path = self.temp / "execution.sqlite"
        self.ledger = ExecutionEvidenceLedger(
            self.path,
            raw_evidence_store=self.raw,
        )
        self.addCleanup(self.ledger.close)

    def raw_sha(self, suffix: str) -> str:
        return self.raw.put(
            f"execution-evidence:{suffix}".encode(),
            source_id="fixture-execution-source",
            retrieved_at_ns=900,
            media_type="application/octet-stream",
            rights_policy_ids=("execution-rights",),
        ).content_sha256

    @staticmethod
    def context(
        *,
        side: OrderSide = OrderSide.BUY,
        order_type: OrderType = OrderType.MARKET,
        marketability: Marketability = Marketability.MARKETABLE,
        size_bucket: str = "SMALL",
        regime: str = "NORMAL",
    ) -> ExecutionContext:
        return ExecutionContext(
            instrument_id="AAPL",
            venue_id=VENUE_ID,
            order_type=order_type,
            side=side,
            marketability=marketability,
            size_bucket=size_bucket,
            regime=regime,
        )

    def outcome(
        self,
        outcome_id: str,
        origin: EvidenceOrigin,
        *,
        version: int = 1,
        side: OrderSide = OrderSide.BUY,
        submitted: str = "10",
        filled: str = "8",
        arrival_price: str = "100",
        fill_price: str | None = "100.20",
        fee: str = "0.80",
        financing: str = "0.00",
        opportunity_cost: str = "0.40",
        submitted_at_ns: int = 1_000,
        acknowledged_at_ns: int = 1_010,
        completed_at_ns: int = 1_050,
        cancelled: bool = False,
        rejected: bool = False,
        raw_sha: str | None = None,
        external_execution_id: str | None = None,
        source_id: str = "fixture-execution-source",
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            outcome_id=outcome_id,
            version=version,
            order_id=f"order:{outcome_id}",
            context=self.context(side=side),
            origin=origin,
            source_id=source_id,
            external_execution_id=(
                f"broker-fill:{outcome_id}"
                if origin is EvidenceOrigin.BROKER_OBSERVED
                and external_execution_id is None
                else external_execution_id
            ),
            raw_content_sha256=(
                self.raw_sha(f"{outcome_id}:{version}")
                if raw_sha is None
                else raw_sha
            ),
            submitted_quantity=Quantity.positive(submitted),
            filled_quantity=Quantity.parse(filled),
            arrival_price=Price.parse("USD", arrival_price, tick_size="0.01"),
            average_fill_price=(
                None
                if fill_price is None
                else Price.parse("USD", fill_price, tick_size="0.01")
            ),
            fee=Money.from_decimal("USD", fee),
            financing=Money.from_decimal("USD", financing),
            opportunity_cost=Money.from_decimal("USD", opportunity_cost),
            submitted_at_ns=submitted_at_ns,
            acknowledged_at_ns=acknowledged_at_ns,
            completed_at_ns=completed_at_ns,
            cancelled=cancelled,
            rejected=rejected,
        )

    def test_origins_are_separate_and_only_broker_is_observed_truth(self) -> None:
        paper = self.outcome("paper", EvidenceOrigin.PAPER)
        synthetic = self.outcome("synthetic", EvidenceOrigin.SYNTHETIC)
        replay = self.outcome("replay", EvidenceOrigin.HISTORICAL_REPLAY)
        broker = self.outcome("broker", EvidenceOrigin.BROKER_OBSERVED)
        for outcome in (paper, synthetic, replay, broker):
            self.assertTrue(self.ledger.append(outcome))

        self.assertFalse(paper.is_observed_truth)
        self.assertFalse(synthetic.is_observed_truth)
        self.assertFalse(replay.is_observed_truth)
        self.assertTrue(broker.is_observed_truth)
        self.assertEqual(
            self.ledger.observed_outcomes(),
            (broker,),
        )
        self.assertEqual(
            self.ledger.outcomes(origin=EvidenceOrigin.PAPER),
            (paper,),
        )
        self.assertEqual(len(self.ledger.outcomes()), 4)

    def test_broker_observation_requires_external_execution_identity(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "BROKER_OBSERVED_EXTERNAL_ID_REQUIRED",
        ):
            self.outcome(
                "missing-external",
                EvidenceOrigin.BROKER_OBSERVED,
                external_execution_id="",
            )

    def test_non_broker_origin_cannot_claim_external_broker_execution(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "NON_BROKER_EXTERNAL_EXECUTION_ID_FORBIDDEN",
        ):
            self.outcome(
                "paper-impersonation",
                EvidenceOrigin.PAPER,
                external_execution_id="broker-fill:fake",
            )

    def test_exact_cost_fill_ratio_latency_and_shortfall_are_deterministic(self) -> None:
        buy = self.outcome("buy", EvidenceOrigin.PAPER)
        self.assertEqual(buy.fill_ratio, Decimal("0.8"))
        self.assertEqual(buy.ack_latency_ns, 10)
        self.assertEqual(buy.completion_latency_ns, 50)
        self.assertEqual(buy.implementation_shortfall_bps, Decimal("20.0000"))
        self.assertEqual(buy.total_explicit_cost.to_decimal(), Decimal("1.20"))

        sell = self.outcome(
            "sell",
            EvidenceOrigin.PAPER,
            side=OrderSide.SELL,
            fill_price="99.80",
        )
        self.assertEqual(sell.implementation_shortfall_bps, Decimal("20.0000"))
        self.assertEqual(buy.sha256(), buy.sha256())

    def test_unfilled_outcome_has_no_fill_price_or_shortfall(self) -> None:
        cancelled = self.outcome(
            "cancelled",
            EvidenceOrigin.PAPER,
            filled="0",
            fill_price=None,
            fee="0",
            opportunity_cost="1.25",
            cancelled=True,
        )
        self.assertEqual(cancelled.fill_ratio, Decimal("0"))
        self.assertIsNone(cancelled.implementation_shortfall_bps)
        self.assertTrue(self.ledger.append(cancelled))

    def test_quantity_timing_currency_and_terminal_state_invariants_fail_closed(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "FILLED_QUANTITY_EXCEEDS_SUBMITTED"):
            self.outcome("overfill", EvidenceOrigin.PAPER, submitted="10", filled="11")
        with self.assertRaisesRegex(InvariantViolation, "FILL_PRICE_REQUIRED"):
            self.outcome("missing-price", EvidenceOrigin.PAPER, filled="1", fill_price=None)
        with self.assertRaisesRegex(InvariantViolation, "UNFILLED_PRICE_FORBIDDEN"):
            self.outcome("phantom-price", EvidenceOrigin.PAPER, filled="0", fill_price="100")
        with self.assertRaisesRegex(InvariantViolation, "REJECTED_OUTCOME_CANNOT_FILL"):
            self.outcome("rejected-fill", EvidenceOrigin.PAPER, rejected=True)
        with self.assertRaisesRegex(InvariantViolation, "OUTCOME_CANNOT_CANCEL_AND_REJECT"):
            self.outcome(
                "double-terminal",
                EvidenceOrigin.PAPER,
                filled="0",
                fill_price=None,
                fee="0",
                cancelled=True,
                rejected=True,
            )
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_TIME_ORDER"):
            self.outcome(
                "bad-time",
                EvidenceOrigin.PAPER,
                acknowledged_at_ns=999,
            )
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_CURRENCY_MISMATCH"):
            replace(
                self.outcome("currency", EvidenceOrigin.PAPER),
                fee=Money.from_decimal("CAD", "1"),
            )

    def test_raw_evidence_must_exist_and_remain_intact(self) -> None:
        missing = self.outcome(
            "missing-raw",
            EvidenceOrigin.PAPER,
            raw_sha="f" * 64,
        )
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_RAW_EVIDENCE_MISSING_OR_CORRUPT"):
            self.ledger.append(missing)

        outcome = self.outcome("tamper-raw", EvidenceOrigin.BROKER_OBSERVED)
        self.ledger.append(outcome)
        self.raw._path(outcome.raw_content_sha256).write_bytes(b"tampered")
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_RAW_EVIDENCE_MISSING_OR_CORRUPT"):
            self.ledger.outcomes()
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_RAW_EVIDENCE_MISSING_OR_CORRUPT"):
            self.ledger.append(outcome)

    def test_versions_are_append_only_idempotent_and_identity_stable(self) -> None:
        original = self.outcome("revision", EvidenceOrigin.BROKER_OBSERVED)
        self.assertTrue(self.ledger.append(original))
        self.assertFalse(self.ledger.append(original))
        conflicting = replace(
            original,
            filled_quantity=Quantity.parse("7"),
        )
        with self.assertRaises(DuplicateConflict):
            self.ledger.append(conflicting)
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_OUTCOME_VERSION_SEQUENCE"):
            self.ledger.append(
                self.outcome(
                    "revision",
                    EvidenceOrigin.BROKER_OBSERVED,
                    version=3,
                )
            )
        correction = self.outcome(
            "revision",
            EvidenceOrigin.BROKER_OBSERVED,
            version=2,
            filled="7",
            fee="0.70",
        )
        self.assertTrue(self.ledger.append(correction))
        self.assertEqual(self.ledger.history("revision"), (original, correction))

        identity_mutation = replace(
            correction,
            context=self.context(side=OrderSide.SELL),
        )
        with self.assertRaises(DuplicateConflict):
            self.ledger.append(identity_mutation)

    def test_database_forbids_update_and_delete(self) -> None:
        outcome = self.outcome("locked", EvidenceOrigin.PAPER)
        self.ledger.append(outcome)
        connection = sqlite3.connect(self.path)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_EXECUTION_EVIDENCE"):
            connection.execute(
                "UPDATE execution_outcomes SET record_json = ? WHERE outcome_id = ?",
                ("{}", outcome.outcome_id),
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_EXECUTION_EVIDENCE"):
            connection.execute(
                "DELETE FROM execution_outcomes WHERE outcome_id = ?",
                (outcome.outcome_id,),
            )
        connection.close()

    def test_stored_record_corruption_is_detected_before_idempotent_return(self) -> None:
        outcome = self.outcome("corrupt", EvidenceOrigin.BROKER_OBSERVED)
        self.ledger.append(outcome)
        self.ledger.close()
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER execution_outcomes_no_update")
        connection.execute(
            "UPDATE execution_outcomes SET record_json = ? WHERE outcome_id = ? AND version = ?",
            ('{"outcome_id":"tampered"}', outcome.outcome_id, outcome.version),
        )
        connection.commit()
        connection.close()
        self.ledger = ExecutionEvidenceLedger(
            self.path,
            raw_evidence_store=self.raw,
        )
        self.addCleanup(self.ledger.close)
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_OUTCOME_HASH_MISMATCH"):
            self.ledger.append(outcome)
        with self.assertRaisesRegex(InvariantViolation, "EXECUTION_OUTCOME_HASH_MISMATCH"):
            self.ledger.history(outcome.outcome_id)

    def test_authority_boundaries_remain_locked(self) -> None:
        self.assertFalse(ExecutionEvidenceLedger.broker_selected)
        self.assertFalse(ExecutionEvidenceLedger.observed_broker_feed_qualified)
        self.assertFalse(ExecutionEvidenceLedger.execution_simulator_calibrated)
        self.assertEqual(ExecutionEvidenceLedger.live_trading_state, "HARD_LOCKED")
        self.assertEqual(ExecutionEvidenceLedger.profitability_state, "UNPROVEN")


if __name__ == "__main__":
    unittest.main()
