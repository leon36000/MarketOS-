# C10 — Execution Simulation and Capacity

Simulation fidelity progresses from bars to trades/quotes, L2 depth, L3 queue reconstruction, broker simulation and shadow/paper/real comparison. A lower stage cannot validate claims belonging to a higher stage.

Every fill model declares marketability, latency, spread, depth, participation, queue assumptions, partial fills, cancellations, rejects, fees, financing and opportunity cost. Costs and fill outcomes are distributions conditioned on instrument, venue, order type, size and regime.

Capacity analysis measures marginal impact, liquidity concentration, turnover, crowding, borrow availability and portfolio interaction. Strategy scale is bounded by the lower confidence limit of net edge after impact and operational constraints.

Observed fills recalibrate a challenger model only after independent review. Synthetic or paper fills are never presented as observed execution truth.
