---
artifact_id: ART-23A-CLAUDE-CODE-CONTRACT-001
version: "0.23.0"
date: 2026-08-04
phase: "23A"
status: "DESIGN_ONLY_SYNTHETIC_BOUNDARY"
---

# Phase 23A Financial World Model Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans. Historical replay remains the authority.

**Goal:** construire un laboratoire multi-fidélité comparant replay historique, ABIDES, JAX-LOB/JaxMARL-HFT, modèles génératifs et scénarios macro/stress.

**Architecture:** common Scenario/Intervention/Trajectory ports, adapters per simulator, metric registry and reality-gap evaluator. Synthetic outputs are physically separated and non-promotable by default.

**Tech Stack:** Python/JAX candidates; ABIDES; JAX-LOB/JaxMARL-HFT; LOB-Bench metrics; Parquet/Arrow candidate; CPU oracle.

**Files:** Create `runtime/world_models/{contracts,replay,abides,jax_lob,generative,macro,evaluator}.py`, `tests/world_models/`, `benchmarks/23A/`, and synthetic evidence under `phases/23A/`.

**Interfaces:** The phase produces `WorldModelScenario`, `Intervention`, `SyntheticEpisode`, `RealityGapReport` and `WorldModelEvaluator.compare_to_replay()`; all generated outputs remain in the synthetic namespace.

## Global Constraints

- `SYNTHETIC_WORLD_MODEL` namespace is mandatory.
- No world model replaces real data or historical replay.
- No strategy edge or live gate can be closed by synthetic performance.
- Every run pins code, weights, cutoff, seed, intervention and compute.

### Task 1: Common contracts
- [ ] Tests RED for missing provenance, seed, cutoff or intervention.
- [ ] Implement Scenario, Intervention, Trajectory, MetricReport and RealityGapReport.

### Task 2: Historical replay oracle adapter
- [ ] Adapt PC-3a/3b replay into the common interface.
- [ ] Verify identical fingerprints and point-in-time boundaries.

### Task 3: ABIDES lane
- [ ] Pin repository/commit and message model.
- [ ] Calibrate agents/latencies against a bounded real sample.
- [ ] Test intervention response and exchange invariants.

### Task 4: JAX-LOB/JaxMARL lane
- [ ] Reproduce CPU reference on small books before GPU scaling.
- [ ] Test vectorized determinism, precision, memory and seed stability.
- [ ] Measure thousands-of-environments claims independently.

### Task 5: Generative LOB lane
- [ ] Add model adapter, train/evaluate only on licensed cutoff data.
- [ ] Test memorization and nearest-neighbor leakage.
- [ ] Use LOB-Bench style distributions and discriminator metrics.

### Task 6: Macro/stress lane
- [ ] Define structural shocks, cross-asset transmission and scenario trees.
- [ ] Preserve assumptions and competing models.

### Task 7: Reality-gap evaluator
- [ ] Compare returns, volatility, spread, depth, imbalance, interarrival, cancel, queue, impact and latency.
- [ ] Test interventions, not only marginal distributions.
- [ ] Produce per-regime failure map and abstention.

### Task 8: Training use gate
- [ ] Allow offline policy training only after scenario provenance and gap limits.
- [ ] Revalidate policies on historical holdout/shadow/paper.
- [ ] Prohibit direct production dependency.

## Exit Gate

`23A_WORLD_MODEL_LAB_LOCAL_GATE_PASS` requires common contracts and reality-gap evaluation. It does not prove realism sufficient for strategy promotion until real-data and intervention gates pass.

## Rollback

Remove adapters/models from active registry, retain synthetic datasets and reports under their namespace, and verify no production route references them.
