from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest

from marketos.capacity import (
    CapacityDistribution,
    CapacityDistributionKind,
    CapacityInputs,
    compute_research_capacity_bound,
)
from marketos.errors import InvariantViolation
from marketos.money import Money


class CapacityTests(unittest.TestCase):
    @staticmethod
    def distribution(
        kind: CapacityDistributionKind,
        p05: str,
        p50: str,
        p95: str,
        *,
        sample_count: int = 100,
    ) -> CapacityDistribution:
        return CapacityDistribution(
            kind=kind,
            p05=Decimal(p05),
            p50=Decimal(p50),
            p95=Decimal(p95),
            sample_count=sample_count,
        )

    def inputs(self, **overrides) -> CapacityInputs:
        values = dict(
            capacity_id="capacity-reversal-001",
            version=1,
            strategy_id="reversal-liquidity",
            strategy_version=1,
            currency="USD",
            gross_edge_bps=self.distribution(
                CapacityDistributionKind.GROSS_EDGE_BPS,
                "20",
                "30",
                "45",
            ),
            impact_bps=self.distribution(
                CapacityDistributionKind.IMPACT_BPS,
                "1",
                "3",
                "5",
            ),
            operating_cost_bps=self.distribution(
                CapacityDistributionKind.OPERATING_COST_BPS,
                "1",
                "2",
                "3",
            ),
            uncertainty_bps=self.distribution(
                CapacityDistributionKind.UNCERTAINTY_BPS,
                "0.5",
                "1",
                "2",
            ),
            liquidity_notional_limit=Money.from_decimal("USD", "1000000"),
            concentration_notional_limit=Money.from_decimal("USD", "600000"),
            turnover_notional_limit=Money.from_decimal("USD", "800000"),
            crowding_notional_limit=Money.from_decimal("USD", "700000"),
            portfolio_interaction_notional_limit=Money.from_decimal(
                "USD",
                "500000",
            ),
            borrow_required=False,
            borrow_available=False,
            borrow_notional_limit=None,
            calibration_report_sha256="a" * 64,
            validation_evidence_sha256="b" * 64,
            shadow_evidence_root_sha256="c" * 64,
            created_at_ns=5_000,
        )
        values.update(overrides)
        return CapacityInputs(**values)

    def test_positive_bound_uses_conservative_edge_and_minimum_constraint(self) -> None:
        result = compute_research_capacity_bound(self.inputs())
        self.assertEqual(result.lower_confidence_net_edge_bps, Decimal("10"))
        self.assertEqual(
            result.research_notional_bound.to_decimal(),
            Decimal("500000.00"),
        )
        self.assertEqual(
            result.binding_constraint,
            "PORTFOLIO_INTERACTION_NOTIONAL_LIMIT",
        )
        self.assertEqual(result.zero_reasons, ())
        self.assertFalse(result.capital_authorized)
        self.assertFalse(result.capacity_qualified)
        self.assertFalse(result.strategy_edge_proven)
        self.assertFalse(result.execution_simulator_calibrated)
        self.assertEqual(result.live_trading_state, "HARD_LOCKED")
        self.assertEqual(result.profitability_state, "UNPROVEN")
        self.assertEqual(result.sha256(), result.sha256())

    def test_non_positive_lower_confidence_edge_returns_zero(self) -> None:
        inputs = self.inputs(
            gross_edge_bps=self.distribution(
                CapacityDistributionKind.GROSS_EDGE_BPS,
                "8",
                "20",
                "30",
            )
        )
        result = compute_research_capacity_bound(inputs)
        self.assertEqual(result.lower_confidence_net_edge_bps, Decimal("-2"))
        self.assertEqual(result.research_notional_bound, Money.zero("USD"))
        self.assertEqual(
            result.zero_reasons,
            ("NON_POSITIVE_LOWER_CONFIDENCE_EDGE",),
        )
        self.assertIsNone(result.binding_constraint)

    def test_every_operational_constraint_is_required(self) -> None:
        cases = (
            (
                "liquidity_notional_limit",
                "MISSING_LIQUIDITY_NOTIONAL_LIMIT",
            ),
            (
                "concentration_notional_limit",
                "MISSING_CONCENTRATION_NOTIONAL_LIMIT",
            ),
            (
                "turnover_notional_limit",
                "MISSING_TURNOVER_NOTIONAL_LIMIT",
            ),
            (
                "crowding_notional_limit",
                "MISSING_CROWDING_NOTIONAL_LIMIT",
            ),
            (
                "portfolio_interaction_notional_limit",
                "MISSING_PORTFOLIO_INTERACTION_NOTIONAL_LIMIT",
            ),
        )
        for field, reason in cases:
            with self.subTest(field=field):
                result = compute_research_capacity_bound(
                    self.inputs(**{field: None})
                )
                self.assertEqual(
                    result.research_notional_bound,
                    Money.zero("USD"),
                )
                self.assertIn(reason, result.zero_reasons)
                self.assertIsNone(result.binding_constraint)

    def test_borrow_requirement_fails_closed(self) -> None:
        unavailable = compute_research_capacity_bound(
            self.inputs(
                borrow_required=True,
                borrow_available=False,
                borrow_notional_limit=Money.from_decimal("USD", "300000"),
            )
        )
        self.assertEqual(unavailable.research_notional_bound, Money.zero("USD"))
        self.assertIn("BORROW_UNAVAILABLE", unavailable.zero_reasons)

        missing_limit = compute_research_capacity_bound(
            self.inputs(
                borrow_required=True,
                borrow_available=True,
                borrow_notional_limit=None,
            )
        )
        self.assertEqual(missing_limit.research_notional_bound, Money.zero("USD"))
        self.assertIn("MISSING_BORROW_NOTIONAL_LIMIT", missing_limit.zero_reasons)

        available = compute_research_capacity_bound(
            self.inputs(
                borrow_required=True,
                borrow_available=True,
                borrow_notional_limit=Money.from_decimal("USD", "300000"),
            )
        )
        self.assertEqual(
            available.research_notional_bound.to_decimal(),
            Decimal("300000.00"),
        )
        self.assertEqual(
            available.binding_constraint,
            "BORROW_NOTIONAL_LIMIT",
        )

    def test_borrow_limit_is_forbidden_when_borrow_is_not_required(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "UNNEEDED_BORROW_LIMIT_FORBIDDEN",
        ):
            self.inputs(
                borrow_required=False,
                borrow_available=True,
                borrow_notional_limit=Money.from_decimal("USD", "300000"),
            )

    def test_distribution_kinds_quantiles_and_samples_are_strict(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "INVALID_CAPACITY_QUANTILES"):
            self.distribution(
                CapacityDistributionKind.GROSS_EDGE_BPS,
                "10",
                "5",
                "20",
            )
        with self.assertRaisesRegex(InvariantViolation, "NEGATIVE_CAPACITY_COST_DISTRIBUTION"):
            self.distribution(
                CapacityDistributionKind.IMPACT_BPS,
                "-1",
                "2",
                "5",
            )
        with self.assertRaisesRegex(InvariantViolation, "INSUFFICIENT_CAPACITY_DISTRIBUTION_SAMPLES"):
            self.distribution(
                CapacityDistributionKind.IMPACT_BPS,
                "1",
                "2",
                "5",
                sample_count=1,
            )
        signed = self.distribution(
            CapacityDistributionKind.GROSS_EDGE_BPS,
            "-10",
            "5",
            "20",
        )
        self.assertEqual(signed.p05, Decimal("-10"))

    def test_input_distribution_kinds_must_match_fields(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "CAPACITY_DISTRIBUTION_KIND_MISMATCH"):
            self.inputs(
                gross_edge_bps=self.distribution(
                    CapacityDistributionKind.IMPACT_BPS,
                    "1",
                    "2",
                    "3",
                )
            )

    def test_constraint_currency_and_positive_amounts_are_strict(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "CAPACITY_CURRENCY_MISMATCH"):
            self.inputs(
                liquidity_notional_limit=Money.from_decimal("CAD", "100000")
            )
        with self.assertRaisesRegex(InvariantViolation, "NON_POSITIVE_CAPACITY_CONSTRAINT"):
            self.inputs(
                liquidity_notional_limit=Money.zero("USD")
            )

    def test_evidence_hashes_and_authority_flags_cannot_be_weakened(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "INVALID_CALIBRATION_REPORT_SHA256"):
            self.inputs(calibration_report_sha256="bad")
        inputs = self.inputs()
        with self.assertRaisesRegex(InvariantViolation, "CAPACITY_CANNOT_AUTHORIZE_CAPITAL"):
            replace(inputs, capital_authorized=True)
        with self.assertRaisesRegex(InvariantViolation, "CAPACITY_CANNOT_PROVE_EDGE"):
            replace(inputs, strategy_edge_proven=True)
        with self.assertRaisesRegex(InvariantViolation, "CAPACITY_CANNOT_CLAIM_CALIBRATED_SIMULATOR"):
            replace(inputs, execution_simulator_calibrated=True)

    def test_equal_constraints_have_deterministic_binding_precedence(self) -> None:
        equal = Money.from_decimal("USD", "500000")
        result = compute_research_capacity_bound(
            self.inputs(
                liquidity_notional_limit=equal,
                concentration_notional_limit=equal,
                turnover_notional_limit=equal,
                crowding_notional_limit=equal,
                portfolio_interaction_notional_limit=equal,
            )
        )
        self.assertEqual(
            result.binding_constraint,
            "LIQUIDITY_NOTIONAL_LIMIT",
        )


if __name__ == "__main__":
    unittest.main()
