# C8 — Derivative Contract and Surface Consistency

Reference data, contract terms, underlying identity, corporate actions, rates, dividends, calendars and quote timestamps must align before model fitting.

Stale, crossed, locked, zero-quality or inconsistent observations are flagged or quarantined. The forward and moneyness convention is explicit.

A fitted surface must pass monotonicity and cross-maturity consistency checks. Violations are preserved as diagnostics rather than hidden by smoothing.

Model family, solver, initial state, constraints, precision, convergence, residuals and output sensitivities are versioned. Risk sensitivities always retain model and numerical uncertainty.

No model is selected by local fixtures. Real chains, contract adjustments and cross-source comparison remain implementation gates.
