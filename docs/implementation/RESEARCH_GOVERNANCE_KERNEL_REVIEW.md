# Research Governance Kernel — Independent Implementation Review

## Scope reviewed

- immutable strategy definitions and search plans;
- append-only retention of successful, failed and abandoned trials;
- hidden-holdout access control and audit receipts;
- chronological rolling walk-forward splits, purging and embargo;
- availability-time look-ahead barriers;
- complete-population multiple-testing evidence;
- distributional cost, capacity and fill assumptions;
- fidelity ordering and synthetic-only limits;
- independent review, rollback and shadow-only promotion.

## TDD evidence

The slice was built through distinct RED-to-GREEN increments:

1. missing strategy and ExperimentBook contracts;
2. missing hidden-holdout isolation;
3. missing purged/embargoed temporal validation;
4. missing complete-population validation evidence;
5. missing independent shadow-only promotion;
6. missing independent ten-check acceptance;
7. adversarial gaps in search-plan enforcement, rolling train windows and post-construction evidence integrity.

Each RED state left the previously completed repository tests passing. The permanent tests retain the negative cases rather than relying on one-time manual review.

## Findings corrected before review closure

1. **Search-plan budget was descriptive rather than authoritative.** Trial ordinals, seeds, parameter names and parameter values are now checked against the exact plan version before append.
2. **`train_window_ns` was anchored to the first fold.** It now advances with every test window and old samples are explicitly accounted as out-of-window purged evidence.
3. **Frozen dataclasses could be bypassed with low-level mutation.** Promotion reconstructs and validates the full request, review and nested validation-evidence graph before evaluating the gate.
4. **Historical fixtures violated their declared plans.** Their seeds and parameter values were aligned with the immutable plan rather than weakening the new controls.
5. **Idempotency could have concealed corrupted stored evidence.** Stored records are decoded and hash-verified before any duplicate response is returned.
6. **Failed and abandoned trials could have been omitted from a statistics subset.** Tried, PBO and Deflated Sharpe populations must each equal the full ledger population.
7. **Calendar and feature controls were previously external to research governance.** The dedicated workflow now runs every prior acceptance verifier before accepting C10 changes.

## Residual gates

This implementation proves local contract behavior, not trading performance. The following still require evidence from later slices and target infrastructure:

- execution simulator calibration against real paper fills;
- parameter-drift, cost-drift and assumption-break monitoring over time;
- independent hidden-holdout evaluation on qualified datasets;
- shadow deployment against real market-data feeds;
- production ExperimentBook storage selection and recovery drills;
- capacity and implementation-shortfall validation at the intended capital scale;
- governance approval for any transition beyond shadow eligibility.

## Authority verdict

```yaml
local_contract_review: NO_BLOCKING_FINDING
shadow_eligibility_ceiling: ENFORCED
strategy_family_selected: false
strategy_edge_proven: false
champion_promoted: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

`NO_BLOCKING_LOCAL_CONFORMANCE_FINDING — REAL_DATA_HOLDOUT_SHADOW_AND_PRODUCTION_QUALIFICATION_REMAIN_OPEN`.
