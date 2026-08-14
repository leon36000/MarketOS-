# C10 — Claude Code Execution Contract

## Objective
Implement a falsifiable Strategy Factory, append-only experiment ledger, temporal validation, multiple-testing controls and execution-fidelity ladder.

## Required surfaces
`runtime/strategy`, `runtime/experiments`, `runtime/validation`, `runtime/simulation`, tests and benchmarks.

## Test-first sequence
1. Hidden holdout access and future data/model/memory/prompt leakage must fail.
2. Every generated trial must remain in the immutable experiment ledger.
3. Purging and embargo remove label overlap and information leakage.
4. PBO/CSCV and Deflated Sharpe include the full tried-strategy population.
5. NO_TRADE and simple baselines are mandatory competitors.
6. Lower-fidelity simulation cannot close a higher-fidelity execution gate.
7. Costs, capacity and fill uncertainty are distributions, not constants.
8. Promotion requires independent approval; drift or broken assumptions trigger fallback.

## Qualification boundary
Local fixtures prove contracts only. Real point-in-time OOS tournaments, execution calibration, capacity and financial edge remain open.

## Rollback
Freeze challengers, restore the previous champion registry, preserve all trials and evidence, and keep live hard locked.
