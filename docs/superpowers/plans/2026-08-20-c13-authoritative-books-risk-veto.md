# C13-0 Authoritative Books and Risk Veto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, reconstructible paper/shadow book journal and a fail-closed C13 risk gate without adding any live or broker route.

**Architecture:** `DurableLedger` wraps the existing exact in-memory `Ledger` and persists canonical journal entries plus hash-chain metadata in SQLite. Append-only ledger-head rows anchor the expected tail, while `checkpoint` derives a `PortfolioSnapshot` only from a real `PortfolioBook` bound to that ledger. `reconcile_book` compares the current durable ledger and supplied snapshot to that checkpoint. `C13RiskGate` accepts only an intact upstream `RiskDecision`, a reconciled book and `PAPER`/`SHADOW` mode.

**Tech Stack:** Python 3.12, standard-library `sqlite3`, existing `dataclasses`, canonical JSON/SHA-256 helpers, `unittest`, repository JSON validators.

**Spec:** `docs/superpowers/specs/2026-08-20-c13-authoritative-books-risk-veto-design.md`

## Global Constraints

- `live_trading_state = HARD_LOCKED`.
- `profitability_state = UNPROVEN`.
- `promotion_allowed = false`.
- Only `PAPER` and `SHADOW` execution modes can pass the C13 gate.
- The 108 canonical requirements remain authoritative; the 119/111 memory discrepancy remains unresolved and non-promotable.
- No broker adapter, OMS/EMS route, optimizer, external service or secret is introduced.
- Every production method added in this lot has a real failing test before its implementation.

---

### Task 1: Durable append-only ledger

**Files:**
- Create: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: `marketos.ledger.JournalEntry`, `marketos.ledger.Ledger`, `marketos.money.Money`, `marketos.portfolio.PortfolioSnapshot`.
- Produces: `DurableLedger(path)`, `post`, `post_many`, `reverse`, `entries`, `balance`, `sha256`, `verify`, `close`, context-manager support.

- [ ] **Step 1: Write the failing persistence test.**

  Add `test_reopen_reconstructs_entries_balances_and_hash` that creates a real temporary SQLite path, posts one balanced USD funding entry, closes the ledger, reopens it and asserts one entry, a 10000-minor-unit cash balance, and the same SHA-256.

- [ ] **Step 2: Run the focused test and confirm the expected RED failure.**

  Run:

  ```bash
  PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books.C13DurableLedgerTests.test_reopen_reconstructs_entries_balances_and_hash -v
  ```

  Expected result: import failure because `marketos.authoritative_books` does not yet exist.

- [ ] **Step 3: Implement the minimal durable wrapper.**

  Define `DurableLedger` with SQLite `WAL` and `synchronous = FULL`, a `ledger_entries` table containing `ledger_sequence`, `entry_id`, `occurred_at_ns`, `record_json`, `record_sha256`, and `previous_sha256`, plus an append-only `ledger_heads` table containing the entry count and cumulative ledger digest. Decode canonical JSON back into `JournalEntry` and `Posting` objects, rebuild an in-memory `Ledger` on open, and reject any digest, sequence, chain or tail-anchor mismatch with `InvariantViolation("JOURNAL_INTEGRITY_FAILURE")`.

- [ ] **Step 4: Run the focused test and confirm GREEN.**

  Run the same command. Expected result: one passing test with no warnings.

- [ ] **Step 5: Add duplicate, conflict and atomic-batch tests.**

  Add these tests and keep each assertion focused:

  ```python
  def test_identical_duplicate_is_idempotent_and_conflict_does_not_mutate(self):
      first = self.entry("fund-1", "100.00")
      conflict = self.entry("fund-1", "101.00")
      with DurableLedger(self.path) as ledger:
          self.assertTrue(ledger.post(first))
          self.assertFalse(ledger.post(first))
          with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
              ledger.post(conflict)
          self.assertEqual(len(ledger.entries()), 1)

  def test_batch_conflict_rolls_back_all_new_entries(self):
      first = self.entry("fund-1", "100.00")
      conflict = self.entry("fund-1", "101.00")
      with DurableLedger(self.path) as ledger:
          with self.assertRaisesRegex(DuplicateConflict, "JOURNAL_ENTRY_ID_CONFLICT"):
              ledger.post_many((first, conflict))
          self.assertEqual(ledger.entries(), ())

  def test_reversal_is_persisted_and_reconstructible(self):
      original = self.entry("fund-1", "100.00")
      with DurableLedger(self.path) as ledger:
          ledger.post(original)
          reversal = ledger.reverse("fund-1", reversal_id="reversal-1", occurred_at_ns=200)
          self.assertEqual(reversal.reversal_of, "fund-1")
      with DurableLedger(self.path) as reopened:
          self.assertEqual(len(reopened.entries()), 2)
          self.assertEqual(reopened.balance("asset:cash:USD", "USD"), Money.zero("USD"))
  ```

  The tests must assert `DuplicateConflict`, unchanged entry count and unchanged balance after a failed batch.

- [ ] **Step 6: Implement the minimum transaction logic and run the focused class.**

  Validate a cloned in-memory ledger before `BEGIN IMMEDIATE`; insert all new rows in one transaction; assign the clone only after `COMMIT`. Use an empty previous digest for the first row and the prior stored record digest thereafter. Run:

  ```bash
  PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books.C13DurableLedgerTests -v
  ```

- [ ] **Step 7: Add tamper and append-only tests, then make them GREEN.**

  Add `test_tampered_record_json_is_detected`, `test_tampered_chain_is_detected`, and `test_sqlite_update_and_delete_are_rejected`. Mutate the database using a separate SQLite connection after closing the wrapper; require `verify()` or reopening to fail closed and require both SQL triggers to reject mutation.

- [ ] **Step 8: Commit the durable ledger slice.**

  ```bash
  git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py
  git commit -m "feat: add durable C13 book ledger"
  ```

### Task 2: Book checkpoints and reconciliation

**Files:**
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: `PortfolioSnapshot` and `DurableLedger`.
- Produces: `BookCheckpoint`, `ReconciliationStatus`, `BookReconciliation`, `DurableLedger.checkpoint(checkpoint_id, book, captured_at_ns=...)`, `DurableLedger.latest_checkpoint`, and `reconcile_book`.

- [ ] **Step 1: Write the failing checkpoint and reconciliation tests.**

  Add `test_checkpoint_survives_reopen_and_reconciles` using a `PortfolioBook` backed by `DurableLedger`; fund it, capture its snapshot, persist a checkpoint, close/reopen, and assert `reconcile_book(reopened, snapshot).status is ReconciliationStatus.RECONCILED`.

  Add `test_snapshot_or_ledger_divergence_is_reported` that changes the snapshot or posts another entry after the checkpoint and asserts `DIVERGENT` with stable reasons `BOOK_SNAPSHOT_MISMATCH` or `CHECKPOINT_STALE`.

- [ ] **Step 2: Run the two tests and verify RED.**

  ```bash
  PYTHONPATH=src python3 -m unittest \
    tests.test_c13_authoritative_books.C13ReconciliationTests -v
  ```

  Expected result: missing checkpoint/reconciliation interfaces.

- [ ] **Step 3: Implement immutable checkpoint records.**

  Add `BookCheckpoint(checkpoint_id, captured_at_ns, snapshot)`, canonical decoding for `Money`, `Quantity`, `Position` and `PortfolioSnapshot`, and an append-only `book_checkpoints` table with sequence, record JSON, record SHA and previous SHA. Require a real `PortfolioBook` whose `ledger is self`; derive its snapshot and require `snapshot.ledger_sha256 == self.sha256()` before persisting. Identical checkpoint redelivery is idempotent; conflicting IDs raise `DuplicateConflict`; an arbitrary snapshot must be rejected with `INVALID_BOOK_CHECKPOINT_SOURCE`.

- [ ] **Step 4: Implement `reconcile_book`.**

  Call `ledger.verify()`, compare the supplied snapshot ledger hash with the current durable hash, compare it with the latest checkpoint, and return an immutable result. Include `status` in the `expected_sha256` input. Bind the result to an opaque provenance capability containing the source ledger object, current journal digest and checkpoint digest; the risk gate must re-verify those live bindings before an allow. Use deterministic reason order: `JOURNAL_INTEGRITY_FAILURE`, `MISSING_BOOK_CHECKPOINT`, `BOOK_LEDGER_HASH_MISMATCH`, `CHECKPOINT_STALE`, `BOOK_SNAPSHOT_MISMATCH`. Return `RECONCILED` only with no reasons.

- [ ] **Step 5: Run the reconciliation tests and full focused module.**

  ```bash
  PYTHONPATH=src python3 -m unittest \
    tests.test_c13_authoritative_books.C13ReconciliationTests -v
  PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books -v
  ```

- [ ] **Step 6: Commit the checkpoint slice.**

  ```bash
  git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py
  git commit -m "feat: add C13 book checkpoints and reconciliation"
  ```

### Task 3: Fail-closed C13 risk gate

**Files:**
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: `RiskDecision`, `RiskAction`, `ExecutionMode`, `BookReconciliation`.
- Produces: `C13GateDecision`, `C13RiskGate.evaluate`.

- [ ] **Step 1: Write the failing gate tests.**

  Add:

  ```python
  def test_reconciled_paper_allow_can_pass_gate(self):
      decision = self.allow_decision()
      reconciliation = self.reconciled_book()
      result = C13RiskGate().evaluate(decision, reconciliation, ExecutionMode.PAPER)
      self.assertEqual(result.action, RiskAction.ALLOW)
      self.assertEqual(result.reasons, ())
      self.assertEqual(result.live_trading_state, "HARD_LOCKED")

  def test_divergent_book_forces_no_trade(self):
      decision = self.allow_decision()
      reconciliation = self.divergent_book("BOOK_SNAPSHOT_MISMATCH")
      result = C13RiskGate().evaluate(decision, reconciliation, ExecutionMode.SHADOW)
      self.assertEqual(result.action, RiskAction.NO_TRADE)
      self.assertIn("BOOKS_UNRECONCILED", result.reasons)

  def test_upstream_veto_and_unknown_mode_remain_no_trade(self):
      decision = self.vetoed_decision("INSUFFICIENT_CASH")
      reconciliation = self.reconciled_book()
      result = C13RiskGate().evaluate(decision, reconciliation, "LIVE")
      self.assertEqual(result.action, RiskAction.NO_TRADE)
      self.assertIn("EXECUTION_MODE_NOT_ALLOWED", result.reasons)
      self.assertIn("UPSTREAM_NO_TRADE", result.reasons)
  ```

  Build a real `RiskDecision` with the existing `RiskKernel`; do not mock it. Assert the result action, stable reasons, decision digest and `live_trading_state`.

- [ ] **Step 2: Run the gate tests and verify RED.**

  ```bash
  PYTHONPATH=src python3 -m unittest \
    tests.test_c13_authoritative_books.C13RiskGateTests -v
  ```

  Expected result: missing `C13RiskGate` and `C13GateDecision`.

- [ ] **Step 3: Implement the minimal immutable gate.**

  Recompute the upstream decision digest from its canonical payload, require `RiskAction.ALLOW`, require `ReconciliationStatus.RECONCILED`, require an actual `ExecutionMode.PAPER` or `ExecutionMode.SHADOW`, and require `HARD_LOCKED`. Otherwise return `NO_TRADE` with ordered reasons `EXECUTION_MODE_NOT_ALLOWED`, `UPSTREAM_NO_TRADE`, `UPSTREAM_DECISION_INTEGRITY_FAILURE`, `BOOKS_UNRECONCILED` and `LIVE_TRADING_LOCK_WEAKENED` as applicable. The module must not import a broker or expose submission methods.

- [ ] **Step 4: Run the focused gate tests and the whole C13 module.**

  ```bash
  PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books.C13RiskGateTests -v
  PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books -v
  ```

- [ ] **Step 5: Commit the risk gate slice.**

  ```bash
  git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py
  git commit -m "feat: add C13 fail-closed risk veto"
  ```

### Task 4: C13 contract artifacts and standalone verifier

**Files:**
- Create: `planning/phases/C13/EXECUTION_CONTRACT.md`
- Create: `planning/phases/C13/C13_DECISIONS.json`
- Create: `planning/phases/C13/C13_REQUIREMENT_CLOSURE.json`
- Create: `docs/implementation/C13_AUTHORITATIVE_BOOKS_RISK_VETO.md`
- Create: `tools/verify_c13_contract.py`
- Test: `tests/test_c13_authoritative_books.py`
- Modify: `MANIFEST.json` via `python3 tools/regenerate_derived.py --root .`

**Interfaces:**
- Consumes: the approved C13-0 spec, the runtime module, and existing requirement IDs `AUD-RSK-001`, `AUD-RSK-004`, `AUD-RSK-005`, `AUD-RSK-006`, `AUD-RSK-009`.
- Produces: a machine-readable non-completion contract and JSON verifier with `ok`, `checks`, `errors`, `live_trading_state`, `profitability_state` and `promotion_allowed`.

- [ ] **Step 1: Write the failing verifier acceptance test.**

  Add `test_c13_validator_reports_non_promotable_verified_slice` that resolves the repository root with `Path(__file__).resolve().parents[1]`, invokes `tools/verify_c13_contract.py --root repository_root --json`, parses JSON, and asserts `ok is True`, all focused checks are true, `live_trading_state == "HARD_LOCKED"`, `profitability_state == "UNPROVEN"`, `promotion_allowed is False`, and `phase_complete is False`. The focused test module must also cover digest/sequence/previous-chain tampering, tail truncation, a SQLite failure injected between batch inserts, late arrival ordering, status tampering, fabricated/stale reconciliation rejection and arbitrary snapshot rejection.

- [ ] **Step 2: Run it and verify RED.**

  ```bash
  PYTHONPATH=src python3 -m unittest \
    tests.test_c13_authoritative_books.C13VerifierTests.test_c13_validator_reports_non_promotable_verified_slice -v
  ```

- [ ] **Step 3: Add the contract artifacts and validator.**

  The contract must map each covered requirement to the runtime, test and validator paths; explicitly list C13-0 exclusions; and preserve the broader `C13_RUNTIME_CONTRACTS` open gap. The verifier must run real temporary-file checks, refuse missing artifacts, and never mutate the repository.

- [ ] **Step 4: Regenerate and validate derived files.**

  ```bash
  python3 tools/regenerate_derived.py --root . --json
  PYTHONPATH=src python3 -m unittest \
    tests.test_c13_authoritative_books.C13VerifierTests -v
  ```

- [ ] **Step 5: Commit the contract slice.**

  ```bash
  git add MANIFEST.json planning/phases/C13/EXECUTION_CONTRACT.md \
    planning/phases/C13/C13_DECISIONS.json \
    planning/phases/C13/C13_REQUIREMENT_CLOSURE.json \
    docs/implementation/C13_AUTHORITATIVE_BOOKS_RISK_VETO.md \
    tools/verify_c13_contract.py tests/test_c13_authoritative_books.py
  git commit -m "feat: verify C13 authoritative books slice"
  ```

### Task 5: Independent verification and integration gate

**Files:**
- Modify only if verification requires an evidenced correction.

- [ ] **Step 1: Run focused and repository verification.**

  ```bash
  PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books -v
  GIT_CONFIG_GLOBAL=/dev/null PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -q
  python3 tools/verify_c13_contract.py --root . --json
  python3 tools/verify_proof_engine.py --root . --json
  python3 tools/verify_proof_binding.py --root . --json
  python3 tools/validate_repository.py --root . --json
  python3 tools/regenerate_derived.py --root . --check --json
  python3 -m compileall -q src tools tests
  git diff --check
  ```

- [ ] **Step 2: Ask `gpt-5.6-sol` for the critical source-state/security gate.**

  The reviewer must inspect the exact branch diff, replay/tamper behavior,
  live-lock boundary, manifest and proof-state binding, and return explicit
  GO/NO-GO with no completion claim.

- [ ] **Step 3: Apply only critical/important review fixes through another RED/GREEN cycle.**

- [ ] **Step 4: Re-run all verification after the review is clean and inspect `git status`.**

- [ ] **Step 5: Push a single bounded PR from this branch.**

  Do not merge to `main` or close the broader C13 gap. Merge only the bounded
  C13-0 PR if GitHub checks and the fresh `gpt-5.6-sol` gate are green.
