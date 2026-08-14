from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import unittest

from marketos.canonical import canonical_json, canonical_sha256
from marketos.errors import InvariantViolation


class Mode(str, Enum):
    PAPER = "PAPER"


@dataclass(frozen=True)
class Sample:
    amount: Decimal
    mode: Mode


class CanonicalTests(unittest.TestCase):
    def test_mapping_order_does_not_change_json_or_hash(self) -> None:
        left = {"b": 2, "a": 1}
        right = {"a": 1, "b": 2}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(canonical_sha256(left), canonical_sha256(right))

    def test_decimal_enum_and_dataclass_are_encoded_exactly(self) -> None:
        encoded = canonical_json(Sample(amount=Decimal("10.5000"), mode=Mode.PAPER))
        self.assertEqual(encoded, '{"amount":{"$decimal":"10.5"},"mode":"PAPER"}')

    def test_float_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "FLOAT_FORBIDDEN"):
            canonical_json({"price": 1.25})

    def test_non_finite_decimal_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "NON_FINITE_DECIMAL"):
            canonical_json(Decimal("NaN"))


if __name__ == "__main__":
    unittest.main()
