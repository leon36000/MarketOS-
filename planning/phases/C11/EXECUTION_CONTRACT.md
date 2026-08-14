# C11 — Claude Code Execution Contract

## Objective
Implement a physically separated multi-fidelity world-model laboratory and constrained offline-RL evaluation stack while historical point-in-time replay remains authoritative.

## Required surfaces
`runtime/world_models`, `runtime/offline_rl`, `tests/world_models`, `tests/offline_rl` and `benchmarks/C11`.

## Test-first sequence
1. Synthetic data must never enter the real-data namespace or close strategy gates.
2. Every world pins source cutoffs, code, weights, seed, intervention and compute.
3. Reality-gap reports compare distributions, temporal dependence and intervention response.
4. Memorization and nearest-neighbour leakage must fail generative-world qualification.
5. RL policies outside behavior support must abstain.
6. OPE estimators, uncertainty and risk constraints must agree within declared bounds.
7. Hidden temporal holdouts remain inaccessible to policy generation.
8. Any candidate still requires historical holdout, shadow and paper evaluation.

## Qualification boundary
Local synthetic fixtures establish interfaces only. Market realism, policy value, execution fidelity and financial edge remain open.

## Rollback
Remove world/policy adapters from registries, retain synthetic evidence, prove historical replay remains unchanged and live remains hard locked.
