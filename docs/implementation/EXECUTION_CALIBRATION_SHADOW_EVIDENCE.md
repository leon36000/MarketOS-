# Execution Calibration, Shadow Evidence and Conservative Capacity

## Status

This slice is **research-only**. It does not select a broker, qualify an observed broker feed, calibrate a production execution simulator, authorize capital, prove strategy edge, prove profitability, or unlock live trading.

Hard boundaries remain:

- `live_trading = HARD_LOCKED`
- `profitability = UNPROVEN`
- `execution_simulator_calibrated = false`
- `observed_broker_feed_qualified = false`
- `capacity_qualified = false`
- `capital_authorized = false`
- `strategy_edge_proven = false`
- `production_backend_selected = false`

## Implemented contracts

### Execution evidence

`src/marketos/execution_evidence.py` separates synthetic, historical replay, paper, shadow-counterfactual and broker-observed origins. Only `BROKER_OBSERVED` is eligible for the observed-truth view. Broker-observed outcomes require an external execution identity and content-addressed raw evidence. SQLite records are append-only and checked for corruption on read and idempotent redelivery.

### Execution model definition and contextual predictions

`src/marketos/execution_calibration.py` makes fill-model assumptions explicit and hashable. Fidelity stages must be contiguous and matched to input capabilities. Predictions are contextual distributions over fill ratio, shortfall, latency, cancellation and rejection; duplicate context predictions are forbidden.

Reality-gap evaluation is per context and per family. Missing contexts, insufficient observations or one failed family cannot be hidden by aggregate performance. Calibration input is restricted to broker-observed evidence.

The calibration gate requires an independent evaluator, human approval, minority findings, no unresolved findings, a rollback plan and exact hash binding. Its maximum positive state is `ELIGIBLE_AS_CHALLENGER`; it cannot mark production or the execution simulator calibrated.

### Shadow evidence

`src/marketos/shadow_evidence.py` records immutable counterfactual trade, no-trade, abstention and cancellation comparisons. Shadow evidence is always `SHADOW_COUNTERFACTUAL`, never observed truth. A separately verified broker-observed outcome may be linked by hash without changing the shadow record's authority.

### Conservative research capacity

`src/marketos/capacity.py` computes a lower-confidence net edge as gross-edge p05 minus impact p95, operating-cost p95 and uncertainty p95. A positive research bound is the minimum complete operational constraint, including borrow when required. Non-positive conservative edge, any missing required constraint, unavailable borrow or incomplete borrow capacity forces a zero bound.

A research capacity bound is not a capital allocation or strategy qualification.

## Independent acceptance

`tools/verify_execution_calibration.py` performs exactly ten independent checks:

1. broker-observed truth firewall;
2. append-only execution evidence;
3. explicit assumptions and contiguous fidelity;
4. strict contextual prediction surfaces;
5. non-maskable reality-gap families;
6. independent-review challenger-only calibration gate;
7. shadow counterfactual truth firewall;
8. append-only shadow evidence;
9. conservative research capacity bound;
10. fail-closed capacity and global authority locks.

`tests/test_execution_calibration_acceptance.py` requires all ten checks and all authority ceilings to remain locked. `.github/workflows/execution-calibration.yml` runs focused tests/verifier first, then repository-wide verification after derived-file reconciliation.

## Non-selection

No broker, feed, execution venue adapter, production model backend, capital allocator or live execution path is selected by this slice. Empirical broker calibration and production eligibility remain future evidence-gated work.