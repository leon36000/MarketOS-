# Research Governance Kernel Implementation Plan

**Status:** `IMPLEMENTED_AND_LOCALLY_VERIFIED — EXACT_HEAD_AND_PR_PUBLICATION_PENDING`

**Goal:** Build a provider-neutral C10 conformance kernel that preserves every strategy trial, prevents hidden-holdout and temporal leakage, proves purging/embargo behavior, and limits any successful candidate to independent-review eligibility for shadow.

**Architecture:** Three standard-library modules separate immutable research records (`experiments.py`), chronological validation (`validation.py`), and evidence-driven promotion (`promotion.py`). SQLite stores append-only canonical records with update/delete triggers and hash verification on every read or idempotent retry. An independent verifier and dedicated workflow execute after all earlier MARKET-OS acceptance layers.

**Tech stack:** Python 3.12 standard library, frozen dataclasses, `Decimal`, SQLite, canonical JSON/SHA-256, `unittest`, GitHub Actions.

## Permanent constraints

- `live_trading_state = HARD_LOCKED` everywhere.
- `profitability_state = UNPROVEN` everywhere.
- Hidden holdout is forbidden to candidate generation, optimization, model councils, prompts, embeddings and memory systems.
- Trial deletion and mutation are forbidden; failed and abandoned trials remain queryable.
- Validation is chronological and point-in-time for features, labels, models, memory, embeddings and prompts.
- Purging removes overlapping labels; embargo removes adjacent post-test samples.
- `NO_TRADE` plus a simple baseline are mandatory.
- PBO/CSCV and Deflated Sharpe populations equal the full tried-trial population.
- Cost, capacity and fill uncertainty are distributions, not scalar assumptions.
- Synthetic-only evidence cannot satisfy a higher-fidelity gate.
- Promotion requires independent review, human approval, minority findings and rollback.
- The highest possible result is `ELIGIBLE_FOR_SHADOW`.
- No strategy family, champion, provider, calibrated simulator or production backend is selected.

## Task 1 — Immutable strategy contracts and ExperimentBook

- [x] Complete immutable `StrategyDefinition` contract.
- [x] Versioned `SearchPlan` with objective, parameter domain, seeds, maximum trials and hidden-holdout identity.
- [x] Append-only `TrialRecord` retention for success, failure and abandonment.
- [x] SQLite `UPDATE`/`DELETE` denial triggers.
- [x] Exact idempotency, conflict rejection and read-time SHA-256 verification.
- [x] Trial ordinals, seeds, parameter names and parameter values constrained by the exact search-plan version.

**Implementation:** `src/marketos/experiments.py`  
**Tests:** `tests/test_experiments.py`, `tests/test_research_governance_adversarial.py`

## Task 2 — Hidden-holdout access and audited receipts

- [x] Fail-closed `DatasetAccessPolicy`.
- [x] Hidden-holdout denial for generators, optimizers, councils, prompts, embeddings and memory.
- [x] Exact independent-evaluator plus `FINAL_EVALUATION` allow case.
- [x] Allowed and denied `AccessReceipt` evidence stored append-only.
- [x] Corruption verification before idempotent redelivery.

**Tests:** `tests/test_holdout_access.py`

## Task 3 — Purged walk-forward and embargo

- [x] Deterministic chronological folds independent of input order.
- [x] Rolling train windows rather than a permanently anchored first window.
- [x] Overlapping-label purge.
- [x] Prior post-test embargo.
- [x] Complete one-category-per-sample accounting in every fold.
- [x] Feature/model/memory/embedding/prompt look-ahead rejection.
- [x] Canonical split-plan and input-root hashes.

**Implementation:** `src/marketos/validation.py`  
**Tests:** `tests/test_validation.py`, `tests/test_research_governance_adversarial.py`

## Task 4 — Complete-population validation evidence

- [x] Mandatory multiple folds, purging and non-zero embargo.
- [x] Mandatory `NO_TRADE` and simple baseline.
- [x] Full tried/PBO/Deflated-Sharpe trial populations, including failed and abandoned trials.
- [x] Ordered, non-negative cost, capacity and fill distributions.
- [x] Contiguous fidelity stages and synthetic-only ceiling.
- [x] Constructor-level evidence graph reconstructed and revalidated at promotion time.
- [x] Diagnostics remain selection controls and cannot set `strategy_edge_proven`.

**Tests:** `tests/test_validation_evidence.py`, `tests/test_research_governance_adversarial.py`

## Task 5 — Independent shadow-only promotion

- [x] `PromotionState` contains only `BLOCKED` and `ELIGIBLE_FOR_SHADOW`.
- [x] Candidate trial must exist and have succeeded.
- [x] Request, evidence, review and complete trial population are hash-bound.
- [x] Unauthorized successful holdout access blocks promotion.
- [x] Independent reviewer distinct from requester.
- [x] Human approval, minority findings and explicit rollback required.
- [x] Unresolved review findings or assumption breaks block promotion.
- [x] Request, review and nested evidence integrity are reconstructed at gate time.
- [x] `champion_promoted = false`, `strategy_edge_proven = false`, `live_trading_state = HARD_LOCKED`.

**Implementation:** `src/marketos/promotion.py`  
**Tests:** `tests/test_promotion.py`, `tests/test_research_governance_adversarial.py`

## Task 6 — Independent acceptance, documentation and CI

- [x] Ten-check independent verifier: `tools/verify_research_governance.py`.
- [x] Acceptance contract: `tests/test_research_governance_acceptance.py`.
- [x] Permanent adversarial suite: `tests/test_research_governance_adversarial.py`.
- [x] Implementation guide: `docs/implementation/RESEARCH_GOVERNANCE_KERNEL.md`.
- [x] Independent review: `docs/implementation/RESEARCH_GOVERNANCE_KERNEL_REVIEW.md`.
- [x] Permanent workflow: `.github/workflows/research-governance.yml`.
- [x] Derived-file reconciliation executes all five successive acceptance verifiers.
- [x] One-shot materialization helpers removed.
- [x] `MANIFEST.json`, requirement index and phase index reconciled.
- [ ] Create a clean user-authored exact-head verification commit.
- [ ] Capture final exact-head workflow IDs and test count.
- [ ] Open the stacked draft PR, record Neon checkpoint and advance the open loop.

## TDD and adversarial evidence

| Stage | RED evidence | GREEN evidence |
|---|---|---|
| ExperimentBook | `bc8eb4967357846fca6e4844771f3c5a272db166` | `09600e2b5b6b93771b47a58a7909d2fe2eb979fb` |
| Holdout isolation | missing access contracts | materializer run `31825276786` |
| Temporal validation | missing `marketos.validation` | `951780978bf8b449afa0e5cf581df824c8b1e83c` |
| Complete evidence | missing baseline/fidelity contracts | materializer run `31825908206` |
| Shadow-only promotion | missing `marketos.promotion` | `92fc235d3a5bf95e4c249017aecaa247bcaff030` |
| Final adversarial review | eight targeted failures on `fc9b1a6da9161ed09a21fa14a75b692099f66d84` | materializer run `31827107627`, commit `641cfcf6a554ea9f362a77ca8e932ca78443fb3a` |
| Permanent CI/docs | stale manifest on first permanent run | reconcile run `31827315256`, commit `3d42cf77940cf5982cf07503f7c38667a30ddbc1` |

## Deliberate non-selection and residual gates

```yaml
strategy_family_selected: false
strategy_edge_proven: false
champion_promoted: false
execution_simulator_calibrated: false
production_backend_selected: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

Real-data hidden-holdout evaluation, calibrated execution simulation, paper/shadow observations, production backend qualification, recovery drills and capital-scale capacity evidence remain later gates. No TODO, TBD or placeholder remains inside the implemented local conformance scope.
