# Research Governance Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral C10 conformance kernel that preserves every strategy trial, prevents hidden-holdout and temporal leakage, proves purging/embargo behavior, and limits any successful candidate to independent-review eligibility for shadow.

**Architecture:** Three focused standard-library modules separate immutable research records (`experiments.py`), chronological validation (`validation.py`), and evidence-driven promotion (`promotion.py`). SQLite stores append-only canonical records with delete/update triggers and hash verification on every read or idempotent retry. Public acceptance is exercised through an independent verifier and a dedicated workflow layered on all earlier MARKET-OS verifiers.

**Tech Stack:** Python 3.12 standard library, frozen dataclasses, `Decimal`, SQLite, canonical JSON/SHA-256 helpers already present in `marketos.canonical`, `unittest`, GitHub Actions.

## Global Constraints

- `live_trading_state = HARD_LOCKED` everywhere.
- `profitability_state = UNPROVEN`; no feature or test may claim financial edge.
- `hidden_holdout_access = FORBIDDEN` for candidate generation, optimization, model council and prompt/memory tools.
- `trial_deletion = FORBIDDEN`; failed and abandoned trials remain queryable.
- Strategy contracts contain the exact C10 fields: strategy ID, hypothesis, mechanism, universe, features, decision rule, position rule, risk budget, execution policy, abstention, failure modes, data cutoffs, code hash and configuration hash.
- Validation is chronological; feature, label, model, memory, embedding and prompt availability may not exceed the evaluation cutoff.
- Purging removes training labels overlapping the test interval; embargo removes adjacent post-test samples.
- `NO_TRADE` and at least one simple baseline are mandatory competitors.
- Multiple-testing evidence represents the full tried-strategy population.
- Synthetic-only evidence and lower-fidelity simulation cannot close higher-fidelity gates.
- Promotion requires independent approval, minority findings and rollback; the highest possible result is `ELIGIBLE_FOR_SHADOW`.
- No external package, provider, strategy family, champion, simulator calibration or production backend is selected.

---

### Task 1: Immutable Strategy Contracts and Append-Only ExperimentBook

**Files:**
- Create: `src/marketos/experiments.py`
- Create: `tests/test_experiments.py`

**Interfaces:**
- Produces: `StrategyDefinition`, `SearchPlan`, `TrialStatus`, `TrialRecord`, `ExperimentLedger`.
- `ExperimentLedger.append_strategy(strategy) -> bool`
- `ExperimentLedger.append_search_plan(plan) -> bool`
- `ExperimentLedger.append_trial(trial) -> bool`
- `ExperimentLedger.strategy_history(strategy_id) -> tuple[StrategyDefinition, ...]`
- `ExperimentLedger.trials(search_id=None) -> tuple[TrialRecord, ...]`

- [ ] Write failing tests for the complete immutable strategy field set, canonical hashes, sequential versions, idempotent exact duplicates and conflicting duplicate rejection.
- [ ] Write failing tests proving successful, failed and abandoned trials remain queryable and that direct SQLite `UPDATE`/`DELETE` operations fail.
- [ ] Write a failing corruption test proving idempotent redelivery verifies the stored canonical record before returning `False`.
- [ ] Run `PYTHONPATH=src python -m unittest tests.test_experiments -v` and confirm missing-module failures.
- [ ] Implement frozen contracts, strict validation, SQLite tables, append-only triggers and read-time hash verification.
- [ ] Re-run the focused tests and commit `feat: add immutable strategy and experiment ledger`.

### Task 2: Hidden-Holdout Access Control and Audited Access Receipts

**Files:**
- Modify: `src/marketos/experiments.py`
- Modify: `tests/test_experiments.py`

**Interfaces:**
- Produces: `DatasetRole`, `DatasetPartition`, `DatasetAccessPolicy`, `AccessDecision`, `AccessReceipt`.
- `DatasetAccessPolicy.authorize(role, partition, purpose, requested_at_ns) -> AccessDecision`
- `ExperimentLedger.append_access_receipt(receipt) -> bool`
- `ExperimentLedger.access_receipts() -> tuple[AccessReceipt, ...]`

- [ ] Write failing tests that deny hidden holdout access to candidate generators, optimizers, model councils, prompts, embeddings and memory systems.
- [ ] Write failing tests that allow a designated independent evaluator only for a declared final-evaluation purpose.
- [ ] Write failing tests proving denied attempts are still appended to the audit ledger and cannot be deleted.
- [ ] Implement fail-closed role/partition authorization and immutable access receipts.
- [ ] Run focused tests and commit `feat: enforce hidden holdout isolation`.

### Task 3: Chronological Walk-Forward Splits with Purging and Embargo

**Files:**
- Create: `src/marketos/validation.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Produces: `TemporalSample`, `WalkForwardConfig`, `TemporalFold`, `SplitPlan`, `build_purged_walk_forward_plan`.
- `build_purged_walk_forward_plan(samples, config) -> SplitPlan`

- [ ] Write failing tests for strict chronological ordering, deterministic output independent of input order, disjoint train/test IDs and complete sample accounting.
- [ ] Write failing tests proving train labels overlapping the test interval are purged and samples inside the post-test embargo are excluded.
- [ ] Write failing tests for look-ahead through feature, model, memory, embedding or prompt availability exceeding the sample decision time.
- [ ] Write failing tests for duplicate sample IDs, overlapping test windows, impossible ranges and configurations that cannot produce a fold.
- [ ] Implement exact nanosecond interval semantics and canonical split-plan hashes.
- [ ] Run `PYTHONPATH=src python -m unittest tests.test_validation -v` and commit `feat: add purged embargoed temporal validation`.

### Task 4: Complete-Population Validation Evidence

**Files:**
- Modify: `src/marketos/validation.py`
- Modify: `tests/test_validation.py`

**Interfaces:**
- Produces: `BaselineKind`, `FidelityStage`, `MetricDistribution`, `MultipleTestingEvidence`, `ValidationEvidence`.
- `ValidationEvidence.validate_against_trials(trials) -> None`

- [ ] Write failing tests requiring `NO_TRADE` plus a simple baseline, multiple chronological folds, purging and embargo evidence.
- [ ] Write failing tests requiring the full tried-strategy population for PBO/CSCV and Deflated Sharpe inputs; omitted failed trials must fail.
- [ ] Write failing tests requiring cost, capacity and fill-uncertainty distributions with ordered quantiles rather than scalar assumptions.
- [ ] Write failing tests preventing synthetic-only evidence and preventing a lower fidelity stage from satisfying a higher claimed gate.
- [ ] Implement validation evidence contracts and population consistency checks without claiming that diagnostic statistics prove edge.
- [ ] Run focused tests and commit `feat: enforce complete validation evidence`.

### Task 5: Independent Shadow-Only Promotion Gate

**Files:**
- Create: `src/marketos/promotion.py`
- Create: `tests/test_promotion.py`

**Interfaces:**
- Produces: `PromotionState`, `PromotionRequest`, `IndependentReview`, `PromotionDecision`, `PromotionGate`.
- `PromotionGate.evaluate(request, evidence, ledger) -> PromotionDecision`

- [ ] Write failing tests requiring all validation stages, exact trial-population consistency, independent reviewer identity, minority findings, explicit rollback and human approval.
- [ ] Write failing tests denying in-sample-only, single-split, hidden-holdout violation, synthetic-only, missing baseline, missing capacity/cost distributions and unresolved assumption breaks.
- [ ] Write failing tests proving a candidate or model council cannot self-promote and that no `LIVE` promotion state exists.
- [ ] Write a passing target test whose strongest result is `ELIGIBLE_FOR_SHADOW` with `champion_promoted = false` and `live_trading_state = HARD_LOCKED`.
- [ ] Implement a deterministic fail-closed promotion gate and commit `feat: add independent shadow-only promotion gate`.

### Task 6: Independent Acceptance, Documentation, CI and Repository Reconciliation

**Files:**
- Create: `tools/verify_research_governance.py`
- Create: `tests/test_research_governance_acceptance.py`
- Create: `docs/implementation/RESEARCH_GOVERNANCE_KERNEL.md`
- Create: `docs/implementation/RESEARCH_GOVERNANCE_KERNEL_REVIEW.md`
- Create: `.github/workflows/research-governance.yml`
- Modify: `.github/workflows/reconcile-derived-files.yml`

**Interfaces:**
- `verify_research_governance() -> dict[str, object]` with exactly ten independent checks.

- [ ] Write acceptance tests requiring 10/10 checks and explicit false values for `strategy_family_selected`, `strategy_edge_proven`, `champion_promoted`, `execution_simulator_calibrated` and `production_backend_selected`.
- [ ] Implement independent checks for immutable trials, hidden holdout, purge/embargo, look-ahead, required baselines, complete population, distributions/fidelity, shadow-only promotion, stored corruption and authority locks.
- [ ] Document implemented behavior, negative findings, deliberate non-selections and rollback semantics.
- [ ] Add the dedicated workflow and include the verifier in derived-file reconciliation.
- [ ] Run focused tests, then `python -m unittest discover -s tests -v`, all earlier verifiers, `python tools/verify_research_governance.py --json`, repository validation, compilation and `git diff --check`.
- [ ] Reconcile `MANIFEST.json`, create a clean exact-head verification commit, update Neon checkpoint/open loop, and open a draft stacked PR.

## Plan Self-Review

- C10 strategy contract fields are represented in Task 1.
- Hidden holdout, trial retention and look-ahead controls are represented in Tasks 1–3.
- Purge, embargo, PBO/CSCV population, Deflated Sharpe population, mandatory baselines, distributions and fidelity are represented in Tasks 3–4.
- Independent approval, minority findings, rollback and shadow-only authority are represented in Task 5.
- No task selects a strategy, proves edge, calibrates a production simulator or creates a live route.
- All public names and method signatures used by later tasks are defined earlier.
- No TODO, TBD or placeholder remains.
