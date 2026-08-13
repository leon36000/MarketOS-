# C4 Durable Workflow Boundary

Temporal is a candidate for long-running provider, repair, reconciliation, settlement, evaluation and recovery workflows. It is not used for the market-data hot path, immediate numerical checks or low-latency routing.

Workflow definitions remain deterministic relative to recorded history. Network, storage, model and external-system effects occur in retry-safe activities with explicit business idempotency and outcome reconciliation.

Workflow code changes require replay/versioning tests. Source and market timestamps remain MARKET-OS event fields rather than workflow time.

Temporal remains optional until its failure recovery and visibility value exceed its persistence, backup, upgrade and operational cost.
