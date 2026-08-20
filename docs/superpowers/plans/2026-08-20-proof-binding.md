# Proof Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the `PROOF_BINDING` evidence gap by binding every recorded PR/CI receipt and authority artifact to exact hashes without promoting partial implementation to complete.

**Architecture:** Add a versioned `PROOF_BINDING.json` ledger containing SHA-256 bindings for the authoritative local artifacts and exact PR/CI receipt records for PR14–PR20. A standalone verifier will compare that ledger against `PR14_PR20_RECONCILIATION.json` and `CURRENT_STATE.json`; the Proof Engine will consume its result as a fail-closed check. The reconciliation will remove only the `PROOF_BINDING` gap after the binding verifier passes; C13–C16 and the 119↔108 memory boundary remain open.

**Tech Stack:** Python 3.12 standard library, JSON, SHA-256, `unittest`, GitHub Actions, derived manifest.

**Spec:** `planning/architecture/PR14_PR20_RECONCILIATION.json`, `planning/architecture/PROOF_ENGINE_POLICY.json`, `authority/CURRENT_STATE.json`, `planning/phases/C16/PHASE_BRIEF.md`.

## Global Constraints

- `authority/CURRENT_STATE.json` remains `planning_phase: C13` and `planning_phase_state: IN_PROGRESS`.
- `live_trading_state` remains `HARD_LOCKED`.
- `profitability_state` remains `UNPROVEN`.
- `software_implementation_complete` remains `false` and broad target nodes remain incomplete.
- The memory set remains an observed 119-row superset; the local 111-row snapshot is not promoted and no rows are invented.
- No runtime GitHub query, remote mutation, commit, push, merge, credential installation, or production selection is performed.

---

### Task 1: Specify the binding contract with failing tests

**Files:**
- Create: `tests/test_proof_binding.py`
- Read: `planning/architecture/PR14_PR20_RECONCILIATION.json`
- Read: `authority/CURRENT_STATE.json`

**Interfaces:**
- Consumes: the future `verify_proof_binding(root: Path | str = ".") -> dict[str, object]` public verifier.
- Produces: tests for pass, missing ledger, source hash tamper, exact SHA mismatch, CI receipt mismatch, and forbidden promotion.

- [ ] **Step 1: Write the failing test**

  Add tests that call `verify_proof_binding` and assert the report has `ok`, `errors`, `bindings_checked`, `artifact_bindings_checked`, and `promotion_allowed` fields. The valid repository test must require seven execution bindings (PR14 through PR20), three artifact bindings, `promotion_allowed == False`, and `ok == True`. Each adversarial test must copy the repository to a temporary directory, mutate exactly one ledger field or bound artifact, and assert the corresponding stable error code.

- [ ] **Step 2: Run the focused test to verify RED**

  Run:

  ```bash
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_proof_binding -v
  ```

  Expected: import failure because `tools.verify_proof_binding` does not exist yet. This confirms the test targets the missing binding seam.

### Task 2: Implement the fail-closed binding ledger and verifier

**Files:**
- Create: `planning/architecture/PROOF_BINDING.json`
- Create: `tools/verify_proof_binding.py`
- Modify: `tests/test_proof_binding.py`

**Interfaces:**
- Consumes: exact hashes of `PR14_PR20_RECONCILIATION.json`, `CURRENT_STATE.json`, and `REQUIREMENT_CROSSWALK.csv`; exact PR14–PR20 head SHAs and CI receipts already recorded in the reconciliation matrix.
- Produces: `verify_proof_binding(root)` returning JSON-serializable evidence with no promotion authority.

- [ ] **Step 1: Add the minimal versioned ledger**

  Record the three authoritative artifact paths and their SHA-256 values, then record PR14, PR15, PR16, PR17, PR18, PR19, and PR20 with exact head SHAs, partial/target roles, positive CI receipt IDs, and `promotable: false`. The ledger must set `authority: "PROOF_BINDING"`, `append_only: true`, and `promotion_allowed: false`.

- [ ] **Step 2: Implement the verifier**

  Load the ledger and reject missing/malformed JSON, absolute or parent-traversal paths, missing artifacts, hash mismatches, duplicate binding IDs, non-40-character lowercase SHA values, receipt mismatches against the reconciliation matrix, state mismatches against `CURRENT_STATE.json`, and any promotion flag set to true. Compare the exact ordered PR set `[14, 15, 16, 17, 18, 19, 20]`; do not query GitHub.

- [ ] **Step 3: Run the focused tests to verify GREEN**

  Run:

  ```bash
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_proof_binding -v
  ```

  Expected: all binding tests pass, including the tamper and receipt mismatch cases.

### Task 3: Integrate Proof Binding with the existing proof and architecture gates

**Files:**
- Modify: `planning/architecture/PROOF_ENGINE_POLICY.json`
- Modify: `tools/verify_proof_engine.py`
- Modify: `tests/test_proof_engine.py`
- Modify: `tests/test_proof_engine_acceptance.py`
- Modify: `planning/architecture/PR14_PR20_RECONCILIATION.json`
- Modify: `tools/verify_architecture_reconciliation.py`
- Modify: `tests/test_architecture_reconciliation_acceptance.py`

**Interfaces:**
- Consumes: `verify_proof_binding(root)` and the existing architecture verifier.
- Produces: a thirteen-check Proof Engine report with `PROOF_BINDING` as a required check and a reconciliation report whose remaining critical gaps are C13, C14, C15, C16, and 119↔108 only.

- [ ] **Step 1: Add the failing integration assertions**

  Extend the proof-engine tests to require `checks_total == 13`, `checks_passed == 13`, and `checks["PROOF_BINDING"] == True`; add a missing/tampered binding regression. Update the architecture acceptance test to assert `PROOF_BINDING` is absent from `critical_open_gaps` while the other safety gaps remain present.

- [ ] **Step 2: Implement the smallest integration**

  Add `planning/architecture/PROOF_BINDING.json` to policy `source_authority_paths`, add `PROOF_BINDING` to the ordered required checks, invoke `verify_proof_binding` in `verify_proof_engine`, and fail with `PROOF_BINDING_INVALID` when it fails. Update the architecture verifier’s required gap set and matrix data only for the now-proven binding gap.

- [ ] **Step 3: Run focused integration tests**

  Run:

  ```bash
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_proof_binding tests.test_proof_engine tests.test_proof_engine_acceptance tests.test_architecture_reconciliation_acceptance -v
  ```

  Expected: all focused tests pass and the proof report returns 13/13 without changing locks or completion state.

### Task 4: Update CI, documentation, manifest, and packaging evidence

**Files:**
- Modify: `.github/workflows/proof-engine-green.yml`
- Modify: `docs/implementation/PROOF_ENGINE_V2.md`
- Modify: `docs/implementation/C16_PACK_BUILDER.md`
- Modify: `MANIFEST.json`
- Test: `tests/test_final_pack.py`

**Interfaces:**
- Consumes: the integrated binding verifier and existing deterministic pack builder.
- Produces: CI coverage for the binding ledger, documentation of thirteen checks, and a manifest-consistent source tree.

- [ ] **Step 1: Add the binding paths to CI and docs**

  Run `python tools/verify_proof_binding.py --json` in the Proof Engine workflow, include all binding paths in both workflow triggers, document the thirteen checks and the non-promotable partial receipts, and preserve the C16 statement that C13–C15 are still required.

- [ ] **Step 2: Regenerate derived files and run the full verification chain**

  Run:

  ```bash
  python3 tools/regenerate_derived.py --root . --json
  python3 tools/regenerate_derived.py --root . --check --json
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
  PYTHONPATH=src python3 tools/verify_proof_binding.py --root . --json
  PYTHONPATH=src python3 tools/verify_proof_engine.py --root . --json
  python3 tools/verify_architecture_reconciliation.py --root . --json
  python3 tools/validate_repository.py --root . --json
  PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q src tools tests
  git diff --check
  ```

- [ ] **Step 3: Rebuild and verify the clean C16 fixture**

  Use `python3 tools/build_claude_pack.py --root <clean-fixture> --output <pack.zip> --verify --json` and require deterministic byte equality, offline verification, exact SHA sidecars, and the unchanged `HARD_LOCKED`/`UNPROVEN`/incomplete boundary.

## Completion evidence

The lot is complete only when the focused RED/GREEN history, thirteen Proof Engine checks, architecture reconciliation, full test suite, derived-manifest check, repository validator, clean deterministic pack verification, and exact output checksums are all fresh and mutually consistent. It is not complete if C13–C15 or the 119↔108 row-level export is inferred from this binding ledger.
