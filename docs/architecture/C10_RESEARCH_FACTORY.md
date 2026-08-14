# C10 — Research Factory and Trial Ledger

Every candidate method is an immutable specification with hypothesis, mechanism, eligible universe, input cutoffs, transformations, decision rule, abstention rule, resource budget, expected failure modes and retirement conditions.

All trials are registered before evaluation. The ledger records parent candidate, generator, code/configuration hashes, dataset versions, temporal cutoffs, parameter space, sampled parameters, seeds, compute, results, failures and reviewer. Failed, duplicated and abandoned trials remain visible.

The generator cannot see hidden evaluation periods, hidden scorer internals or results from future periods. An evaluation service receives a sealed artifact and returns a signed result. Repeated inspection of a holdout consumes its governance budget and can invalidate it.

Baseline comparisons include no action, simple transparent methods and lower-complexity versions. Complexity is admitted only when incremental out-of-sample value survives uncertainty, implementation cost and operational risk.

Candidate creation and candidate promotion are separate authorities. Automation can generate challengers; it cannot promote the active baseline.
