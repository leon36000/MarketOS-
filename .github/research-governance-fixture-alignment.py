#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one fixture patch site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_experiments.py",
    '''            parameters={
                "spread_z": Decimal("2.0") + Decimal(ordinal) / Decimal("10"),
                "max_holding_bars": 2,
            },
            seed=ordinal if seed is None else seed,
''',
    '''            parameters={
                "spread_z": (
                    Decimal("1.5"),
                    Decimal("2.0"),
                    Decimal("2.5"),
                )[ordinal - 1],
                "max_holding_bars": 2,
            },
            seed=(7, 11, 19)[ordinal - 1] if seed is None else seed,
''',
)

replace_once(
    "tests/test_promotion.py",
    '''            parameters={"threshold": Decimal("1.5") + Decimal(ordinal) / 10},
            seed=ordinal,
''',
    '''            parameters={
                "threshold": (
                    Decimal("1.5"),
                    Decimal("2.0"),
                    Decimal("1.5"),
                )[ordinal - 1]
            },
            seed=(7, 11, 19)[ordinal - 1],
''',
)

replace_once(
    "tools/verify_research_governance.py",
    '''        parameters={"threshold": Decimal("1.5") + Decimal(ordinal) / 10},
        seed=ordinal,
''',
    '''        parameters={
            "threshold": (
                Decimal("1.5"),
                Decimal("2.0"),
                Decimal("1.5"),
            )[ordinal - 1]
        },
        seed=(7, 11, 19)[ordinal - 1],
''',
)
