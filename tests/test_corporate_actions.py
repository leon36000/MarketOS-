from __future__ import annotations

from decimal import Decimal
import unittest
from uuid import UUID

from marketos.corporate_actions import (
    ActionFamily,
    ActionStatus,
    AdjustmentFactor,
    AdjustmentSeries,
    CorporateActionBook,
    CorporateActionVersion,
)
from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.money import Price


ACTION_ID = UUID("00000000-0000-0000-0000-000000000300")
INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000000001")


class CorporateActionTests(unittest.TestCase):
    @staticmethod
    def action(version: int, *, available_ns: int, status: ActionStatus, ratio: str) -> CorporateActionVersion:
        return CorporateActionVersion(
            action_id=ACTION_ID,
            version=version,
            instrument_id=INSTRUMENT_ID,
            family=ActionFamily.SPLIT,
            status=status,
            announcement_ns=50,
            ex_date_ns=200,
            record_date_ns=210,
            effective_date_ns=200,
            payable_date_ns=None,
            expiration_date_ns=None,
            first_seen_at_ns=available_ns,
            available_to_strategy_at_ns=available_ns,
            revision_time_ns=available_ns,
            source_id="primary-exchange",
            terms={"new_shares": ratio, "old_shares": "1"},
        )

    def test_corrections_and_cancellations_are_append_only(self) -> None:
        book = CorporateActionBook()
        v1 = self.action(1, available_ns=100, status=ActionStatus.ANNOUNCED, ratio="2")
        v2 = self.action(2, available_ns=150, status=ActionStatus.CORRECTED, ratio="3")
        v3 = self.action(3, available_ns=180, status=ActionStatus.CANCELLED, ratio="3")
        self.assertTrue(book.append(v1))
        self.assertTrue(book.append(v2))
        self.assertTrue(book.append(v3))

        self.assertIsNone(book.as_known(ACTION_ID, knowledge_time_ns=99))
        self.assertEqual(book.as_known(ACTION_ID, knowledge_time_ns=120), v1)
        self.assertEqual(book.as_known(ACTION_ID, knowledge_time_ns=160), v2)
        self.assertEqual(book.as_known(ACTION_ID, knowledge_time_ns=200), v3)
        self.assertEqual(len(book.history(ACTION_ID)), 3)

    def test_duplicate_version_is_idempotent_but_conflict_fails(self) -> None:
        book = CorporateActionBook()
        v1 = self.action(1, available_ns=100, status=ActionStatus.ANNOUNCED, ratio="2")
        self.assertTrue(book.append(v1))
        self.assertFalse(book.append(v1))
        conflicting = self.action(1, available_ns=100, status=ActionStatus.ANNOUNCED, ratio="4")
        with self.assertRaises(DuplicateConflict):
            book.append(conflicting)
        with self.assertRaisesRegex(InvariantViolation, "ACTION_VERSION_SEQUENCE"):
            book.append(self.action(3, available_ns=200, status=ActionStatus.CORRECTED, ratio="4"))

    def test_future_action_does_not_enter_effective_query(self) -> None:
        book = CorporateActionBook()
        book.append(self.action(1, available_ns=250, status=ActionStatus.ANNOUNCED, ratio="2"))
        self.assertEqual(
            book.effective_between(0, 300, knowledge_time_ns=249),
            (),
        )
        self.assertEqual(len(book.effective_between(0, 300, knowledge_time_ns=250)), 1)

    def test_adjustment_is_separate_from_raw_price_and_bitemporal(self) -> None:
        raw = Price.parse("USD", "100", tick_size="0.01")
        series = AdjustmentSeries()
        factor = AdjustmentFactor(
            factor_id=UUID("00000000-0000-0000-0000-000000000301"),
            version=1,
            instrument_id=INSTRUMENT_ID,
            applies_before_ns=200,
            factor=Decimal("0.5"),
            available_to_strategy_at_ns=250,
            source_action_sha256="a" * 64,
        )
        series.append(factor)
        self.assertIsNone(
            series.adjust(raw, INSTRUMENT_ID, raw_time_ns=100, knowledge_time_ns=249)
        )
        adjusted = series.adjust(raw, INSTRUMENT_ID, raw_time_ns=100, knowledge_time_ns=250)
        self.assertEqual(raw.value, Decimal("100"))
        self.assertEqual(adjusted.adjusted_price.value, Decimal("50"))
        self.assertEqual(adjusted.raw_price, raw)
        self.assertEqual(adjusted.factor_sha256, factor.sha256())


if __name__ == "__main__":
    unittest.main()
