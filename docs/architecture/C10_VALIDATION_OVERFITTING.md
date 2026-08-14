# C10 — Temporal Validation and Overfitting Controls

Validation is chronological. Labels, features, universe membership, model weights, embeddings, memory and prompts are cut off by their true availability.

Purged walk-forward evaluation removes training observations whose labels overlap the test interval; an embargo protects adjacent observations when dependence can persist. Holdouts remain hidden from candidate generators and optimizers.

Combinatorially symmetric cross-validation estimates the probability of backtest overfitting from the complete candidate population. Deflated Sharpe adjusts for non-normal returns, track length and selection among multiple trials. These diagnostics complement, rather than replace, economic and regime tests.

The ledger records every trial, parameter, seed and negative result. Search stopping, metric changes and deleted trials are auditable. A strategy cannot be promoted from a single split, in-sample result or post-selected narrative.
