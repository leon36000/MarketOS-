#!/usr/bin/env python3
from pathlib import Path

path = Path("tests/test_shadow_evidence.py")
text = path.read_text(encoding="utf-8")
old = '''        with self.assertRaises(DuplicateConflict):
            self.ledger.append(
                replace(original, opportunity_fill_ratio=Decimal("0.50"))
            )
'''
new = '''        with self.assertRaises(DuplicateConflict):
            self.ledger.append(
                replace(
                    original,
                    opportunity_fill_ratio=Decimal("0.50"),
                    fill_ratio_gap=Decimal("-0.30"),
                )
            )
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one shadow fixture patch site, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
