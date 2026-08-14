# C7 — Claude Code Execution Contract

## Objective

Implement point-in-time filing facts, transparent accounting-quality evidence and scenario-based valuation behind provider-neutral interfaces.

## Required surfaces

```text
runtime/fundamentals/contracts.py
runtime/fundamentals/filings.py
runtime/fundamentals/normalization.py
runtime/fundamentals/quality.py
runtime/valuation/contracts.py
runtime/valuation/scenarios.py
tests/fundamentals/
tests/valuation/
benchmarks/C7/
```

## Test-first sequence

1. A later amendment must remain invisible to an earlier context.
2. Unit, period or dimensional mismatch must block silent aggregation.
3. Structured tags conflicting with the filed document must create a discrepancy record.
4. Original and amended facts must both remain reproducible.
5. Quality flags must expose evidence and known false-positive conditions.
6. Valuation must output scenarios, sensitivities and abstention rather than only one number.
7. Historical factor experiments must retain inactive securities, filing lags, costs and multiple-testing controls.

## Qualification boundary

Local fixtures validate contracts only. Real filing capture, normalized-provider reconciliation, method selection and out-of-sample value remain separate gates.

## Rollback

Remove the signed C7 delta, restore the C6 checkpoint, regenerate derived files and preserve every filing discrepancy and rejected normalization.
