# R13 source-content retrieval contract

This branch closes one bounded R13 prephase gap: **current-runtime retrieval and hashing of official and primary research content**.

It does not close R13, select a technology, implement a feature store, construct a production dataset, or alter trading locks.

## Evidence boundary

```text
HTTPS locator
→ allowlisted final domain
→ exact response bytes in private CI workspace
→ byte count + SHA-256 + response metadata
→ fail-closed rights record
→ receipt-only deterministic ZIP
```

Raw source bytes are not uploaded as an artifact. Their hashes and retrieval metadata are shared. Redistribution, commercial use, model training, and derivative-data rights remain unasserted pending legal and provider review.

## Tests before implementation

The contract suite was written first and initially failed because the retrieval module did not exist. The implemented suite verifies:

- HTTPS-only, credential-free locators;
- explicit domain allowlists, including redirect targets;
- duplicate locator and source-ID rejection;
- fail-closed rights classification;
- response status, content-type, empty-body, and maximum-size checks;
- exact SHA-256 over response bytes;
- required versus optional failure behavior;
- category and total-success thresholds;
- omission of private raw bytes and private paths from the shared bundle;
- deterministic ZIP bytes from identical inputs;
- internal JSON, SHA, byte-count, and bundle-manifest consistency.

## R13 bootstrap

```yaml
semantic_head:
  phase: R12
  revision: 3
  sha256: 08ff66fb5f630a654d624f4b85927834fbbdeeb71b5c17891d3691513cc181a9
bootstrap_snapshot:
  id: 1ed9c62f-c68f-4a2d-9c1c-c056703a821d
  sha256: e241796dbfc59ef9d7e0f451bb7157fef6c7829900742260af5e00071fa264d9
bootstrap_checkpoint: 12121212-1212-4212-8212-121212121234
R13_phase_events: 0
```

## Scope

The content-addressed root manifest assembles category-specific source shards and covers primary research on backtest overfitting, selection-adjusted inference, dependent validation and causal ML, plus official documentation for:

- time-series and group-aware validation;
- point-in-time feature retrieval;
- data and table versioning;
- lineage and experiment tracking;
- data validation and drift checks;
- causal estimation and refutation;
- label-quality and weak-supervision methods.

Every software or statistical method remains a **bakeoff candidate**. `technology_adoptions = 0`.

## Immutable locks

```yaml
live_trading: HARD_LOCKED
profitability: UNPROVEN
false_done: FORBIDDEN
stubs: FORBIDDEN
project_complete: false
production_ready: false
```
