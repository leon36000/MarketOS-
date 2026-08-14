# Research Governance Kernel — Implementation Slice

## Purpose

This slice implements the C10 research-governance contracts that must exist before MARKET-OS may compare, reject or advance strategy candidates. It preserves negative evidence, prevents temporal and holdout leakage, and limits the strongest possible decision to eligibility for an independently controlled shadow evaluation.

It does not select a strategy family, prove predictive edge, calibrate a production execution simulator or authorize live trading.

## Implemented contracts

### Immutable strategy and search plans

`StrategyDefinition` records the falsifiable hypothesis, mechanism, universe, features, decision rule, position rule, risk budget, execution policy, abstention conditions, failure modes, data cutoffs, code hash and configuration hash.

`SearchPlan` versions the objective metric, parameter domain, random seeds, maximum trial count and hidden-holdout identity. A trial is admitted only when:

- its ordinal is within the declared search budget;
- its seed was declared before the search;
- its parameter names exactly match the plan;
- every parameter value belongs to the declared domain;
- its strategy and plan versions are exact matches.

Changing a metric, stopping rule or search domain requires a new append-only plan version.

### Append-only ExperimentBook

The SQLite conformance ledger stores strategy versions, search-plan versions, terminal trials and dataset-access receipts. Exact redelivery is idempotent only after the stored canonical record and SHA-256 digest have been reverified. Conflicting reuse fails closed.

Database triggers reject `UPDATE` and `DELETE`. Successful, failed and abandoned trials remain queryable and participate in the complete tried-strategy population.

### Hidden-holdout isolation

`DatasetAccessPolicy` denies hidden-holdout access to candidate generators, optimizers, model councils, prompt systems, embedding systems and memory systems. Only an `INDEPENDENT_EVALUATOR` using the exact `FINAL_EVALUATION` purpose may receive an allow decision.

Allowed and denied attempts are both preserved as immutable `AccessReceipt` evidence. An unauthorized successful hidden-holdout receipt blocks promotion; a denied and audited attempt does not silently disappear.

### Purged walk-forward validation

`build_purged_walk_forward_plan` produces deterministic rolling-window folds independent of input order. Every sample belongs to exactly one category in every fold:

- train;
- test;
- purged because its label overlaps the test interval or falls outside the rolling train window;
- embargoed because it lies inside a prior post-test embargo;
- future relative to the current test interval.

Feature, model, memory, embedding and prompt availability must not exceed the sample decision time. Test windows are chronological, non-overlapping and separated by the configured embargo.

### Complete validation evidence

`ValidationEvidence` requires:

- multiple chronological folds;
- explicit purging and non-zero embargo;
- `NO_TRADE` plus at least one simple baseline;
- PBO/CSCV and Deflated Sharpe populations matching every tried trial, including failures and abandonments;
- distributions for costs, capacity and fill uncertainty rather than scalar assumptions;
- a contiguous fidelity chain from synthetic to the claimed stage;
- no synthetic-only escalation to historical or shadow authority.

All nested evidence is reconstructed and revalidated at promotion time so object mutation cannot bypass constructor-level controls. These diagnostics govern selection risk; they do not independently establish financial edge.

### Independent shadow-only promotion

`PromotionGate` binds a request, validation evidence, independent review and complete trial-population hash. It requires:

- a successful candidate trial inside the exact search scope;
- complete validation evidence through event replay;
- no unauthorized hidden-holdout success;
- an independent evaluator distinct from the requester;
- explicit approval, a human approval identifier and preserved minority findings;
- no unresolved review findings or broken assumptions;
- an explicit rollback to a safe state such as `NO_TRADE`.

The only states are `BLOCKED` and `ELIGIBLE_FOR_SHADOW`. There is no `LIVE` state and no automatic champion activation.

## Independent acceptance

`tools/verify_research_governance.py` executes ten independent checks:

1. immutable complete trial evidence;
2. hidden-holdout isolation and audit;
3. purged and embargoed walk-forward splits;
4. feature/model/memory/embedding/prompt look-ahead barriers;
5. mandatory `NO_TRADE` and simple baselines;
6. complete multiple-testing population;
7. distributional costs, capacity, fills and fidelity ordering;
8. independent shadow-only promotion;
9. stored research-evidence corruption detection;
10. authority locks and deliberate non-selection.

## Deliberate non-selection

The following remain outside this conformance slice:

- strategy-family selection;
- calibrated production execution simulation;
- exchange or broker qualification;
- target infrastructure benchmarking;
- live shadow observations on real feeds;
- production experiment database selection;
- any claim of edge, capacity at deployed scale or profitability.

```yaml
strategy_family_selected: false
strategy_edge_proven: false
champion_promoted: false
execution_simulator_calibrated: false
production_backend_selected: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```
