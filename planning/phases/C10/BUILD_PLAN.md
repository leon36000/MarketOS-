# C10 Build Plan

Create immutable specifications, complete run records, temporal partitions and evidence-level labels.

Modules:

```text
runtime/research/contracts.py
runtime/research/ledger.py
runtime/research/time_splits.py
runtime/research/evidence_levels.py
tests/research/
benchmarks/C10/
```

Tests verify hidden periods, complete run records, exclusion of overlapping observations, simple baselines and level-appropriate conclusions.

No component is selected by local fixtures. Rollback restores the previous registry and keeps negative results.
