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
from marketos.shadow_evidence import (
    ShadowComparison,
    ShadowDecision,
    ShadowEvidenceLedger,
)


VENUE_ID = UUID("00000000-0000-0000-0000-000000014010")


class ShadowEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-shadow-evidence-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.raw = RawEvidenceStore(self.temp / "raw")
        self.addCleanup(self.raw.close)
        self.execution = ExecutionEvidenceLedger(
            self.temp / "execution.sqlite",
            raw_evidence_store=self.raw,
        )
        self.addCleanup(self.execution.close)
        self.path = self.temp / "shadow.sqlite"
        self.ledger = ShadowEvidenceLedger(
            self.path,
            raw_evidence_store=self.raw,
            execution_evidence_ledger=self.execution,
        )
        self.addCleanup(self.ledger.close)

    @staticmethod
    def context() -> ExecutionContext:
        return ExecutionContext(
            instrument_id="AAPL",
            venue_id=VENUE_ID,
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            marketability=Marketability.MARKETABLE,
            size_bucket="SMALL",
            regime="NORMAL",
        )

    def raw_sha(self, suffix: str) -> str:
        return self.raw.put(
            f"shadow-evidence:{suffix}".encode(),
            source_id="shadow-reference-fixture",
            retrieved_at_ns=900,
            media_type="application/octet-stream",
            rights_policy_ids=("shadow-rights",),
        ).content_sha256

    def broker_outcome(
        self,
        outcome_id: str,
        *,
        origin: EvidenceOrigin = EvidenceOrigin.BROKER_OBSERVED,
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            outcome_id=outcome_id,
            version=1,
            order_id=f"order:{outcome_id}",
            context=self.context(),
            origin=origin,
            source_id="broker-fixture",
            external_execution_id=(
                f"external:{outcome_id}"
                if origin is EvidenceOrigin.BROKER_OBSERVED
                else None
            ),
            raw_content_sha256=self.raw_sha(f"execution:{outcome_id}"),
            submitted_quantity=Quantity.positive("10"),
            filled_quantity=Quantity.parse("8"),
            arrival_price=Price.parse("USD", "100", tick_size="0.01"),
            average_fill_price=Price.parse(
                "USD",
                "100.04",
                tick_size="0.01",
            ),
            fee=Money.from_decimal("USD", "0.80"),
            financing=Money.zero("USD"),
            opportunity_cost=Money.from_decimal("USD", "0.40"),
            submitted_at_ns=1_000,
            acknowledged_at_ns=1_010,
            completed_at_ns=1_050,
            cancelled=False,
            rejected=False,
        )

    def trade_comparison(
        self,
        comparison_id: str = "shadow-trade",
        *,
        version: int = 1,
        linked_broker_outcome_sha256: str | None = None,
        raw_sha: str | None = None,
    ) -> ShadowComparison:
        return ShadowComparison(
            comparison_id=comparison_id,
            version=version,
            strategy_id="reversal-liquidity",
            strategy_version=1,
            decision=ShadowDecision.TRADE_INTENT,
            decision_reason="Point-in-time signal and risk checks allowed intent",
            intent_id=f"intent:{comparison_id}",
            intent_sha256="a" * 64,
            context=self.context(),
            prediction_sha256="b" * 64,
            model_definition_sha256="c" * 64,
            reference_market_sha256="d" * 64,
            source_dataset_sha256="e" * 64,
            raw_content_sha256=(
                self.raw_sha(f"{comparison_id}:{version}")
                if raw_sha is None
                else raw_sha
            ),
            decision_time_ns=1_000,
            prediction_available_at_ns=1_000,
            later_observation_available_at_ns=1_100,
            predicted_fill_ratio=Decimal("0.80"),
            predicted_shortfall_bps=Decimal("4.0"),
            opportunity_fill_ratio=Decimal("0.60"),
            opportunity_shortfall_bps=Decimal("6.0"),
            fill_ratio_gap=Decimal("-0.20"),
            shortfall_gap_bps=Decimal("2.0"),
            linked_broker_outcome_sha256=linked_broker_outcome_sha256,
            broker_fill_claimed=False,
        )

    def no_trade_comparison(
        self,
        comparison_id: str,
        decision: ShadowDecision,
        *,
        opportunity_fill_ratio: str | None = "1.0",
    ) -> ShadowComparison:
        return ShadowComparison(
            comparison_id=comparison_id,
            version=1,
            strategy_id="reversal-liquidity",
            strategy_version=1,
            decision=decision,
            decision_reason=(
                "Required state was missing"
                if decision is ShadowDecision.ABSTAIN
                else "Expected net edge was non-positive"
            ),
            intent_id=None,
            intent_sha256=None,
            context=self.context(),
            prediction_sha256=None,
            model_definition_sha256=None,
            reference_market_sha256="d" * 64,
            source_dataset_sha256="e" * 64,
            raw_content_sha256=self.raw_sha(comparison_id),
            decision_time_ns=1_000,
            prediction_available_at_ns=1_000,
            later_observation_available_at_ns=1_100,
            predicted_fill_ratio=None,
            predicted_shortfall_bps=None,
            opportunity_fill_ratio=(
                None
                if opportunity_fill_ratio is None
                else Decimal(opportunity_fill_ratio)
            ),
            opportunity_shortfall_bps=(
                None
                if opportunity_fill_ratio is None
                else Decimal("2.0")
            ),
            fill_ratio_gap=None,
            shortfall_gap_bps=None,
            linked_broker_outcome_sha256=None,
            broker_fill_claimed=False,
        )

    def test_trade_counterfactual_has_exact_discrepancies_but_is_not_truth(self) -> None:
        comparison = self.trade_comparison()
        self.assertEqual(comparison.evidence_origin, EvidenceOrigin.SHADOW_COUNTERFACTUAL)
        self.assertFalse(comparison.is_observed_truth)
        self.assertEqual(comparison.fill_ratio_gap, Decimal("-0.20"))
        self.assertEqual(comparison.shortfall_gap_bps, Decimal("2.0"))
        self.assertTrue(comparison.missed_opportunity)
        self.assertTrue(self.ledger.append(comparison))
        self.assertEqual(self.ledger.comparisons(), (comparison,))
        self.assertEqual(self.ledger.observed_links(), ())

    def test_no_trade_and_abstention_are_preserved_with_missed_opportunity(self) -> None:
        no_trade = self.no_trade_comparison(
            "no-trade",
            ShadowDecision.NO_TRADE,
        )
        abstention = self.no_trade_comparison(
            "abstain",
            ShadowDecision.ABSTAIN,
        )
        self.ledger.append(no_trade)
        self.ledger.append(abstention)
        self.assertTrue(no_trade.missed_opportunity)
        self.assertTrue(abstention.missed_opportunity)
        self.assertEqual(
            self.ledger.comparisons(decision=ShadowDecision.NO_TRADE),
            (no_trade,),
        )
        self.assertEqual(
            self.ledger.comparisons(decision=ShadowDecision.ABSTAIN),
            (abstention,),
        )

    def test_pure_shadow_record_cannot_claim_broker_fill(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "SHADOW_BROKER_FILL_CLAIM_FORBIDDEN",
        ):
            replace(self.trade_comparison(), broker_fill_claimed=True)
        self.assertFalse(hasattr(self.trade_comparison(), "external_execution_id"))

    def test_trade_intent_requires_intent_prediction_and_opportunity(self) -> None:
        comparison = self.trade_comparison()
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_INTENT_REQUIRED"):
            replace(comparison, intent_id=None)
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_PREDICTION_REQUIRED"):
            replace(comparison, prediction_sha256=None)
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_OPPORTUNITY_REQUIRED"):
            replace(comparison, opportunity_fill_ratio=None)

    def test_non_trade_decision_cannot_contain_intent_or_prediction(self) -> None:
        comparison = self.no_trade_comparison(
            "no-trade-fields",
            ShadowDecision.NO_TRADE,
        )
        with self.assertRaisesRegex(InvariantViolation, "NON_TRADE_SHADOW_INTENT_FORBIDDEN"):
            replace(
                comparison,
                intent_id="intent:forbidden",
                intent_sha256="a" * 64,
            )
        with self.assertRaisesRegex(InvariantViolation, "NON_TRADE_SHADOW_PREDICTION_FORBIDDEN"):
            replace(
                comparison,
                prediction_sha256="b" * 64,
                model_definition_sha256="c" * 64,
            )

    def test_discrepancies_must_match_prediction_and_opportunity_exactly(self) -> None:
        comparison = self.trade_comparison()
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_FILL_RATIO_GAP_MISMATCH"):
            replace(comparison, fill_ratio_gap=Decimal("0"))
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_SHORTFALL_GAP_MISMATCH"):
            replace(comparison, shortfall_gap_bps=Decimal("0"))
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_RATIO_OUT_OF_RANGE"):
            replace(comparison, opportunity_fill_ratio=Decimal("1.1"))

    def test_prediction_and_later_observation_times_are_point_in_time(self) -> None:
        comparison = self.trade_comparison()
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_PREDICTION_LOOKAHEAD"):
            replace(comparison, prediction_available_at_ns=1_001)
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_OBSERVATION_BEFORE_DECISION"):
            replace(comparison, later_observation_available_at_ns=999)

    def test_valid_broker_link_is_verified_but_does_not_change_origin(self) -> None:
        broker = self.broker_outcome("broker-linked")
        self.execution.append(broker)
        comparison = self.trade_comparison(
            "linked-shadow",
            linked_broker_outcome_sha256=broker.sha256(),
        )
        self.ledger.append(comparison)
        self.assertEqual(
            self.ledger.observed_links(),
            ((comparison.comparison_id, broker.sha256()),),
        )
        self.assertFalse(comparison.is_observed_truth)
        self.assertEqual(comparison.evidence_origin, EvidenceOrigin.SHADOW_COUNTERFACTUAL)

    def test_unknown_or_non_broker_link_is_rejected(self) -> None:
        unknown = self.trade_comparison(
            "unknown-link",
            linked_broker_outcome_sha256="f" * 64,
        )
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_BROKER_LINK_NOT_FOUND"):
            self.ledger.append(unknown)

        paper = self.broker_outcome(
            "paper-link",
            origin=EvidenceOrigin.PAPER,
        )
        self.execution.append(paper)
        comparison = self.trade_comparison(
            "paper-linked-shadow",
            linked_broker_outcome_sha256=paper.sha256(),
        )
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_BROKER_LINK_NOT_OBSERVED"):
            self.ledger.append(comparison)

    def test_raw_evidence_is_verified_on_append_read_and_duplicate(self) -> None:
        missing = self.trade_comparison(
            "missing-raw",
            raw_sha="f" * 64,
        )
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_RAW_EVIDENCE_MISSING_OR_CORRUPT"):
            self.ledger.append(missing)

        comparison = self.trade_comparison("tamper-raw")
        self.ledger.append(comparison)
        self.raw._path(comparison.raw_content_sha256).write_bytes(b"tampered")
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_RAW_EVIDENCE_MISSING_OR_CORRUPT"):
            self.ledger.comparisons()
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_RAW_EVIDENCE_MISSING_OR_CORRUPT"):
            self.ledger.append(comparison)

    def test_versions_are_append_only_and_identity_stable(self) -> None:
        original = self.trade_comparison("versioned")
        self.assertTrue(self.ledger.append(original))
        self.assertFalse(self.ledger.append(original))
        with self.assertRaises(DuplicateConflict):
            self.ledger.append(
                replace(
                    original,
                    opportunity_fill_ratio=Decimal("0.50"),
                    fill_ratio_gap=Decimal("-0.30"),
                )
            )
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_VERSION_SEQUENCE"):
            self.ledger.append(
                self.trade_comparison("versioned", version=3)
            )
        correction = self.trade_comparison(
            "versioned",
            version=2,
        )
        self.assertTrue(self.ledger.append(correction))
        self.assertEqual(self.ledger.history("versioned"), (original, correction))
        with self.assertRaises(DuplicateConflict):
            self.ledger.append(
                replace(correction, context=replace(self.context(), regime="STRESS"))
            )

    def test_database_mutation_and_stored_corruption_fail_closed(self) -> None:
        comparison = self.trade_comparison("locked")
        self.ledger.append(comparison)
        connection = sqlite3.connect(self.path)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_SHADOW_EVIDENCE"):
            connection.execute(
                "UPDATE shadow_comparisons SET record_json = ? WHERE comparison_id = ?",
                ("{}", comparison.comparison_id),
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_SHADOW_EVIDENCE"):
            connection.execute(
                "DELETE FROM shadow_comparisons WHERE comparison_id = ?",
                (comparison.comparison_id,),
            )
        connection.close()

        self.ledger.close()
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER shadow_comparisons_no_update")
        connection.execute(
            "UPDATE shadow_comparisons SET record_json = ? WHERE comparison_id = ? AND version = ?",
            ('{"comparison_id":"tampered"}', comparison.comparison_id, comparison.version),
        )
        connection.commit()
        connection.close()
        self.ledger = ShadowEvidenceLedger(
            self.path,
            raw_evidence_store=self.raw,
            execution_evidence_ledger=self.execution,
        )
        self.addCleanup(self.ledger.close)
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_COMPARISON_HASH_MISMATCH"):
            self.ledger.history(comparison.comparison_id)
        with self.assertRaisesRegex(InvariantViolation, "SHADOW_COMPARISON_HASH_MISMATCH"):
            self.ledger.append(comparison)

    def test_authority_boundaries_remain_locked(self) -> None:
        self.assertFalse(ShadowEvidenceLedger.broker_selected)
        self.assertFalse(ShadowEvidenceLedger.shadow_deployment_qualified)
        self.assertFalse(ShadowEvidenceLedger.execution_simulator_calibrated)
        self.assertFalse(ShadowEvidenceLedger.strategy_edge_proven)
        self.assertEqual(ShadowEvidenceLedger.live_trading_state, "HARD_LOCKED")
        self.assertEqual(ShadowEvidenceLedger.profitability_state, "UNPROVEN")


if __name__ == "__main__":
    unittest.main()
