# C13 — Deterministic Risk Kernel

The Risk Kernel is independent from strategies, models, optimizers and the cockpit. It consumes reconciled books, effective limits, data/clock quality, market state, liquidity, capacity, stress and a signed expiring OrderIntent.

Controls include gross/net exposure, concentration, leverage, cash, factor/sector/country/currency exposure, liquidity, participation, borrow, options Greeks, loss/drawdown, tail stress, order size/rate and operational health.

Outputs are allow, resize, hedge-required, NO_TRADE, cancel-all, trading halt or quarantine. A veto is absolute. Unknown inputs, stale limits, unsupported instruments, uncertain positions or failed dependencies deny risk increase.

The optimizer proposes feasible allocations under uncertainty, cost and capacity. It cannot silently relax a constraint or declare feasibility. The Risk Kernel validates the resulting intent independently.

Kill switch and cancel-all are deterministic, locally available and tested without an LLM, GUI or cloud dependency.
