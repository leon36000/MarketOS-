# Execution Calibration and Shadow Evidence Implementation Plan

**Status:** `IN_PROGRESS`

**Goal:** Implement provider-neutral execution-evidence contracts that keep simulated/paper fills physically and semantically separate from observed broker truth, compare fill-model predictions against distributional observations by context, preserve shadow discrepancies, and compute conservative research-only capacity bounds without declaring the production simulator calibrated.

**Source basis:**

- `docs/architecture/C10_EXECUTION_SIMULATION.md`
- `planning/phases/C10/C10_DECISIONS.json`
- `docs/architecture/C11_REALITY_GAP.md`
- `planning/phases/C11/EXECUTION_CONTRACT.md`
- `planning/phases/C11/C11_DECISIONS.json`
- Neon retrieval receipt `e90debb8-fe88-492b-a3f0-5fb591dea698`

**Architecture:** Four standard-library modules separate immutable execution evidence (`execution_evidence.py`), distributional model evaluation (`execution_calibration.py`), shadow comparisons (`shadow_evidence.py`) and conservative capacity analysis (`capacity.py`). SQLite ledgers remain append-only and content verified. All qualification decisions are independent-review bound and capped below production calibration or live authority.

## Permanent constraints

- `live_trading_state = HARD_LOCKED`.
- `profitability_state = UNPROVEN`.
- `execution_simulator_calibrated = false` for this local conformance slice.
- Synthetic, historical replay, paper and shadow-counterfactual evidence may never be presented as observed broker truth.
- Only `BROKER_OBSERVED` evidence can enter an observed calibration set.
- Every fill model explicitly declares marketability, latency, spread, depth, participation, queue, partial-fill, cancellation, reject, fee, financing and opportunity-cost assumptions.
- Calibration is contextual by instrument, venue, order type, size bucket and regime.
- Every material reality-gap family is reported separately; no aggregate score may hide a failed family or bucket.
- Challenger recalibration requires independent review and preserved minority findings.
- Local fixtures may prove interfaces only; they cannot close production-feed, broker, latency, capacity or financial-promotion gates.
- Shadow evidence is immutable counterfactual evidence and never observed execution truth.
- Capacity is a research bound using the lower-confidence net edge after impact and operational constraints; it is not deployable capital authorization.

## Task 1 — Immutable execution-evidence ledger and truth firewall

**Files:**
- Create `src/marketos/execution_evidence.py`
- Create `tests/test_execution_evidence.py`

- [ ] Define `EvidenceOrigin`, `Marketability`, `ExecutionContext`, `FillOutcome` and `ExecutionEvidenceLedger`.
- [ ] Require exact source, context, submitted/filled quantity, arrival/fill prices, fees, financing, opportunity cost, latency, cancellation/reject state and raw-evidence hash.
- [ ] Verify raw content through `RawEvidenceStore` before append and on every read/idempotent retry.
- [ ] Keep observed-truth queries restricted to `BROKER_OBSERVED` and reject namespace impersonation.
- [ ] Preserve synthetic, replay, paper, shadow and observed records append-only with database update/delete triggers.
- [ ] Add corruption, duplicate, identity, quantity, timing and origin-firewall tests.

## Task 2 — Explicit fill-model assumptions and contextual predictions

**Files:**
- Create `src/marketos/execution_calibration.py`
- Create `tests/test_execution_calibration.py`

- [ ] Define ordered `FidelityStage` values S0–S5.
- [ ] Define immutable `ExecutionAssumptions` covering every C10 assumption family.
- [ ] Define `FillModelDefinition`, contextual `QuantileDistribution` and `PredictedExecutionDistribution`.
- [ ] Require contiguous fidelity, exact code/config/dependency hashes, training cutoff and immutable context keys.
- [ ] Reject missing assumptions, invalid quantiles, probability ranges, duplicate contexts and higher-fidelity claims without required inputs.

## Task 3 — Reality-gap report and independently reviewed challenger decision

**Files:**
- Modify `src/marketos/execution_calibration.py`
- Modify `tests/test_execution_calibration.py`

- [ ] Build observed distributions only from verified `BROKER_OBSERVED` outcomes.
- [ ] Compare fill ratio, shortfall, latency, cancellation and reject families separately per context.
- [ ] Require declared tolerance and minimum observations for every family/bucket.
- [ ] Surface every failed family and bucket; no aggregate pass can mask one.
- [ ] Define `CalibrationReview`, `CalibrationDecision` and `CalibrationGate` with only `BLOCKED` or `ELIGIBLE_AS_CHALLENGER`.
- [ ] Require an independent reviewer, human approval, minority findings and a rollback plan.
- [ ] Keep `production_calibrated = false` and `execution_simulator_calibrated = false`.

## Task 4 — Immutable shadow comparison ledger

**Files:**
- Create `src/marketos/shadow_evidence.py`
- Create `tests/test_shadow_evidence.py`

- [ ] Record candidate intent, model prediction, reference market state, later observable opportunity and discrepancy metrics without sending an order.
- [ ] Prohibit any broker fill claim for a pure shadow record.
- [ ] Preserve no-trade decisions, abstentions, cancellations and missed-opportunity evidence.
- [ ] Verify source hashes and append-only storage before idempotent redelivery.
- [ ] Keep shadow evidence out of observed calibration truth unless separately linked to an actual broker-observed record.

## Task 5 — Conservative research-only capacity bounds

**Files:**
- Create `src/marketos/capacity.py`
- Create `tests/test_capacity.py`

- [ ] Define distributions for gross edge, impact, operating costs and uncertainty.
- [ ] Include liquidity concentration, turnover, crowding, borrow availability and portfolio interaction constraints.
- [ ] Compute lower-confidence net edge and bind research notional by the minimum operational constraint.
- [ ] Return zero when lower-confidence edge is non-positive, borrow is unavailable or any required constraint is missing.
- [ ] Keep `capital_authorized = false` and `strategy_edge_proven = false`.

## Task 6 — Independent acceptance, review, CI and memory

**Files:**
- Create `tools/verify_execution_calibration.py`
- Create `tests/test_execution_calibration_acceptance.py`
- Create `docs/implementation/EXECUTION_CALIBRATION_SHADOW_EVIDENCE.md`
- Create `docs/implementation/EXECUTION_CALIBRATION_SHADOW_EVIDENCE_REVIEW.md`
- Create `.github/workflows/execution-calibration.yml`
- Modify `.github/workflows/reconcile-derived-files.yml`

- [ ] Implement exactly ten independent acceptance checks.
- [ ] Run all earlier verifiers plus the new verifier and full repository suite.
- [ ] Reconcile manifest and indices.
- [ ] Publish a clean exact-head commit and draft stacked PR.
- [ ] Record final workflow evidence, checkpoint, decision and next open loop in Neon.

## Deliberate non-selection

```yaml
broker_selected: false
observed_broker_feed_qualified: false
execution_simulator_calibrated: false
challenger_model_selected: false
capacity_qualified: false
capital_authorized: false
strategy_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```
