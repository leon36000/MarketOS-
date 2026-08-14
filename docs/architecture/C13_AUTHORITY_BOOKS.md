# C13 — Authoritative Books

MARKET-OS maintains separate books for observations, reference identity, investments, decisions, executions, risk, models, experiments and evidence. A service may derive a view but cannot silently rewrite another book.

Cash, positions, lots, orders, fills, fees and limits are event-sourced with exact units, effective time, knowledge time, source, version and hash. Derived balances are rebuildable from append-only records.

Cross-book differences create reconciliation events. Unexplained divergence blocks risk-increasing actions and is never averaged away. Current state is authoritative only after source freshness, sequence completeness and reconciliation pass.

The DecisionBook records distributions, assumptions, abstentions and the deterministic tool evidence used. A profitable outcome does not rewrite the quality of the original decision.
