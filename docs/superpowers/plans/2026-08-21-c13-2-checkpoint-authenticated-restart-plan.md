# C13-2 Checkpoint-Authenticated Restart Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a non-empty paper/shadow authoritative book after restart only when the latest checkpoint is authenticated by a versioned sidecar and exactly matches the verified ledger head.

**Architecture:** Extend the existing durable sidecar from a ledger-head witness to a version-2 witness covering both ledger and checkpoint heads. Load and validate the entire append-only checkpoint chain before restoring the latest snapshot; legacy sidecars remain readable for audit but cannot authorize restoration. Every malformed, stale, missing, or mismatched state remains fail-closed.

**Tech Stack:** Python 3.12, `sqlite3`, canonical JSON, SHA-256 content addressing, `unittest`, existing MarketOS ledger/portfolio/risk modules.

**Spec:** `docs/superpowers/specs/2026-08-21-c13-2-checkpoint-authenticity-reconstruction-design.md`

## Global Constraints

- `live_trading_state = HARD_LOCKED`.
- `profitability_state = UNPROVEN`.
- `phase_complete = false`.
- `promotion_allowed = false`.
- `external_order_submission = FORBIDDEN`.
- C13-0 and C13-1 validators must remain green.
- An actor rewriting both SQLite and the independent sidecar remains out of scope; no automatic repair is permitted.
- Existing C13-0/C13-1 source receipts must be refreshed only to bind the current descendant source tree; their partial-slice boundaries must not be promoted.
- Every changed manifest-listed file requires `python3 tools/regenerate_derived.py --root . --json` before validation.

---

### Task 1: Add failing C13-2 runtime tests

**Files:**
- Modify: `tests/test_c13_authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: current `DurableLedger`, `AuthoritativePortfolioBook`, `BookCheckpoint`, `PortfolioSnapshot`, and existing SQLite test helpers.
- Produces: executable red tests that define the v2 witness, bootstrap, snapshot-validation, and restart-restore contract.

- [ ] **Step 1: Add a valid v2 restart restoration test.**

Create a funding checkpoint, close the ledger, reopen it, call
`authoritative_book(base_currency="USD")`, and assert that its snapshot,
cash, positions, realized P&L, and `ledger_sha256` equal the checkpoint.

```python
def test_reopen_restores_latest_authenticated_checkpoint(self) -> None:
    with DurableLedger(self.path) as ledger:
        book = ledger.authoritative_book(base_currency="USD")
        book.fund("fund-1", Money.from_decimal("USD", "100.00"), occurred_at_ns=100)
        snapshot = book.snapshot()
        ledger.checkpoint("checkpoint-1", book, captured_at_ns=100)

    with DurableLedger(self.path) as reopened:
        restored = reopened.authoritative_book(base_currency="USD")
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(reopened.latest_checkpoint().snapshot, snapshot)
```

- [ ] **Step 2: Add red bootstrap and legacy tests.**

Cover these exact cases: deleting the sidecar for an existing empty database
raises `JOURNAL_INTEGRITY_FAILURE`; a version-1 sidecar can be opened for
verification but `authoritative_book` on a non-empty ledger raises
`BOOK_CHECKPOINT_WITNESS_REQUIRED`; a genuinely new path creates a v2 genesis
sidecar.

- [ ] **Step 3: Add red checkpoint-witness tamper tests.**

Drop only the checkpoint update trigger, rewrite a checkpoint snapshot,
recompute its SQLite `record_sha256`, and assert reopening or restoration
fails because the sidecar still carries the original checkpoint digest.
Also mutate checkpoint sequence, previous hash, sidecar checkpoint digest,
and sidecar version independently; each case must fail closed.

- [ ] **Step 4: Add red snapshot invariant tests.**

Construct tampered checkpoint records for duplicate/out-of-order positions,
invalid instrument identifiers, wrong currencies, negative or non-finite
quantities/costs, non-zero cost on zero quantity, invalid ledger digest,
cash mismatch, and `captured_at_ns` earlier than the greatest ledger event.
Each test must assert a stable `BOOK_CHECKPOINT_*` or `BOOK_SNAPSHOT_*`
failure and that no authoritative book is published.

- [ ] **Step 5: Run the focused tests to confirm RED.**

Run:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest tests.test_c13_authoritative_books -v
```

Expected: the new C13-2 tests fail because v2 witness fields and restore
behavior do not yet exist. Existing C13-0/C13-1 tests must remain otherwise
diagnosable; do not weaken their assertions.

- [ ] **Step 6: Commit the red test contract.**

```bash
git add tests/test_c13_authoritative_books.py
git commit -m "test: define C13-2 authenticated restart behavior"
```

### Task 2: Implement v2 sidecar bootstrap and witness loading

**Files:**
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: the existing SQLite ledger/head/checkpoint tables and v1 anchor format.
- Produces: v2 anchor payloads with `anchor_version`, `checkpoint_sequence`, and `checkpoint_record_sha256`; deterministic bootstrap and legacy flags.

- [ ] **Step 1: Record pre-open filesystem state.**

Before opening SQLite, capture `path_existed_before_open = self.path.exists()`
and `anchor_existed_before_open = self.anchor_path.exists()`. Use the existing
row counts after schema creation to distinguish a new path from an existing
database whose sidecar was deleted.

- [ ] **Step 2: Define exact v2 anchor payload helpers.**

Implement `_checkpoint_witness_payload()` returning `(0, "")` when no
checkpoint exists or `(latest_sequence, latest_record_sha256)` for the actual
latest row. Extend `_anchor_payload(ledger)` to return the existing ledger
fields plus:

```python
{
    "anchor_version": "2.0.0",
    "checkpoint_sequence": checkpoint_sequence,
    "checkpoint_record_sha256": checkpoint_record_sha256,
}
```

Make `anchor_sha256` cover every payload key using existing canonical hashing.

- [ ] **Step 3: Implement bootstrap and legacy classification.**

Write a v2 genesis anchor only for a genuinely new path with zero ledger,
head, and checkpoint rows. Reject a missing anchor for an existing database.
Accept v1 anchors for audit/reconciliation while setting an internal
`_checkpoint_witness_version = "1.0.0"`; do not upgrade them automatically.
Require v2 for non-empty authoritative restoration.

- [ ] **Step 4: Run bootstrap tests and the focused suite.**

Run the new bootstrap tests first, then:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest tests.test_c13_authoritative_books -v
```

Expected: bootstrap tests pass; restoration and snapshot tests remain RED.

- [ ] **Step 5: Commit the sidecar/bootstrap slice.**

```bash
git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py
git commit -m "feat: version C13 checkpoint witness bootstrap"
```

### Task 3: Add exact checkpoint and snapshot validation

**Files:**
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: `BookCheckpoint`, `PortfolioSnapshot`, verified `Ledger`, and `Money`/`Quantity`/`Position` types.
- Produces: `_validate_checkpoint_for_restore(checkpoint, ledger)` that raises stable fail-closed invariant codes and returns no mutable state.

- [ ] **Step 1: Add exact digest and scalar validators.**

Require lowercase 64-character hexadecimal digests. Require non-negative
integer `captured_at_ns`, `captured_at_ns >= max(entry.occurred_at_ns)`,
uppercase three-letter currencies, finite integer money minor units, finite
non-negative quantities, and finite non-negative average costs.

- [ ] **Step 2: Add canonical position and cash validators.**

Require strictly increasing trimmed instrument identifiers, no duplicates,
zero quantity only with zero average cost, equal currencies throughout the
snapshot, and snapshot cash exactly equal to
`ledger.balance(f"asset:cash:{base_currency}", base_currency)`.

- [ ] **Step 3: Bind validation to the current ledger head.**

Require `checkpoint.snapshot.ledger_sha256 == ledger.sha256()` and reject
missing, stale, or future checkpoint state. Validate the checkpoint’s
captured time against the verified journal before any book is allocated.

- [ ] **Step 4: Run each invariant test individually.**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_c13_authoritative_books.C13CheckpointReconstructionTests.test_checkpoint_rewrite_with_recomputed_digest_is_rejected -v
PYTHONPATH=src python3 -m unittest \
  tests.test_c13_authoritative_books.C13CheckpointReconstructionTests.test_snapshot_cash_mismatch_is_rejected -v
```

Expected: each targeted test passes; no malformed snapshot reaches
`_authoritative_book`.

- [ ] **Step 5: Commit validation.**

```bash
git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py
git commit -m "feat: validate C13 checkpoint snapshots fail closed"
```

### Task 4: Restore only an authenticated current-head checkpoint

**Files:**
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: v2 checkpoint witness and `_validate_checkpoint_for_restore`.
- Produces: `DurableLedger.authoritative_book(base_currency: str)` that restores a verified current-head checkpoint or raises a fail-closed invariant.

- [ ] **Step 1: Load and verify the complete checkpoint chain before restore.**

Ensure `_load_checkpoints()` verifies every sequence, canonical record,
record digest and `previous_sha256`, then compare the actual latest row with
the v2 sidecar checkpoint sequence and record digest. The sidecar must not be
used to select an older matching checkpoint.

- [ ] **Step 2: Restore privately, then publish.**

For a non-empty ledger, require v2 witness, latest checkpoint, exact current
ledger digest, and all snapshot invariants. Construct an
`AuthoritativePortfolioBook`, call its existing `_restore_snapshot`, recompute
`snapshot()`, compare it to the checkpoint, and assign
`self._authoritative_book` only after equality succeeds.

- [ ] **Step 3: Preserve fresh-ledger behavior.**

An empty verified ledger still creates a new authoritative book. A non-empty
ledger without an authenticated current-head checkpoint continues to raise
`BOOK_RECONSTRUCTION_REQUIRED` or the more specific
`BOOK_CHECKPOINT_WITNESS_REQUIRED`; no fallback book is returned.

- [ ] **Step 4: Add restore/race tests and run the C13 suite.**

Cover successful restoration, stale checkpoint, legacy sidecar, no
checkpoint, sidecar mismatch, and a writer advancing the ledger before
publication. Run:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest tests.test_c13_authoritative_books -v
```

Expected: all C13 authoritative-book tests pass.

- [ ] **Step 5: Commit restoration.**

```bash
git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py
git commit -m "feat: restore authenticated C13 books after restart"
```

### Task 5: Make checkpoint witness updates rollback-safe

**Files:**
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_authoritative_books.py`, `tests/test_c13_execution_safety.py`

**Interfaces:**
- Consumes: existing `checkpoint()` and `execution_transaction()` rollback boundaries.
- Produces: sidecar updates that cannot leave an apparently trusted checkpoint after a failed SQLite or filesystem operation.

- [ ] **Step 1: Capture prior sidecar bytes for regular checkpoints.**

Before a checkpoint transaction, save the exact existing anchor bytes. Write
the v2 payload only after the checkpoint row is present in the open SQLite
transaction. On any exception, rollback SQLite and restore the prior bytes.

- [ ] **Step 2: Preserve execution-transaction ordering.**

Keep the current C13-1 ordering: checkpoint witness replacement happens
before SQLite commit; commit failure restores database, in-memory book,
checkpoint list, and sidecar. A witness replacement failure must mark no
checkpoint as trusted.

- [ ] **Step 3: Add failure-injection tests.**

Inject sidecar replacement failure and SQLite commit failure; assert prior
anchor bytes, ledger digest, checkpoint list and book snapshot are unchanged.
Add the database-only checkpoint rewrite test that recomputes the SQLite row
digest and proves the independent sidecar rejects it.

- [ ] **Step 4: Run focused execution and authoritative tests.**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_c13_authoritative_books tests.test_c13_execution_safety -v
```

- [ ] **Step 5: Commit rollback hardening.**

```bash
git add src/marketos/authoritative_books.py tests/test_c13_authoritative_books.py tests/test_c13_execution_safety.py
git commit -m "test: prove C13 checkpoint witness rollback safety"
```

### Task 6: Add C13-2 evidence contract and standalone validator

**Files:**
- Create: `docs/implementation/C13_2_CHECKPOINT_AUTHENTICATED_RESTART.md`
- Create: `planning/phases/C13/C13_2_DECISIONS.json`
- Create: `planning/phases/C13/C13_2_REQUIREMENT_CLOSURE.json`
- Create: `planning/phases/C13/C13_2_EXECUTION_CONTRACT.md`
- Create: `planning/phases/C13/C13_2_SOURCE_RECEIPT.json`
- Create: `tools/verify_c13_checkpoint_reconstruction.py`
- Modify: `planning/phases/C13/C13_SOURCE_RECEIPT.json`
- Test: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Consumes: C13-2 runtime/tests and the approved spec.
- Produces: JSON validator output with `slice = "C13-2"`, `status = "VERIFIED_SLICE"`, `phase_complete = false`, `promotion_allowed = false`, and explicit legacy/witness/lock checks.

- [ ] **Step 1: Write evidence documents from the approved spec.**

Record the exact runtime boundary, required files, failure codes, legacy
policy, simultaneous rewrite exclusion, rollback, and commands. Do not claim
full C13 completion or live readiness.

- [ ] **Step 2: Implement validator required-artifact and boundary checks.**

The validator must load C13-2 decisions/closure/current state, assert all
hard locks, verify required paths, run the C13-2 runtime scenarios in a
temporary directory, and report each check separately. It must exit 0 only
when all checks pass while retaining `phase_complete=false` and
`promotion_allowed=false`.

- [ ] **Step 3: Refresh the descendant C13-0 source receipt.**

Update `planning/phases/C13/C13_SOURCE_RECEIPT.json` after runtime/test/tool
changes so its source hashes match the current descendant tree and its
`source_parent_commit` remains an ancestor. Keep its `slice = C13-0` and
partial boundary unchanged.

- [ ] **Step 4: Add the C13-2 source receipt.**

Record all C13-2 source paths and hashes except the receipt itself, the
source-tree digest, the exact ancestor commit, and `promotion_allowed=false`.

- [ ] **Step 5: Add the validator subprocess test.**

Run `tools/verify_c13_checkpoint_reconstruction.py --root . --json`
from the test suite and assert return code 0, `ok=true`, all checks true,
`phase_complete=false`, and `promotion_allowed=false`.

- [ ] **Step 6: Commit the evidence and validator.**

```bash
git add docs/implementation/C13_2_CHECKPOINT_AUTHENTICATED_RESTART.md \
  planning/phases/C13/C13_2_DECISIONS.json \
  planning/phases/C13/C13_2_REQUIREMENT_CLOSURE.json \
  planning/phases/C13/C13_2_EXECUTION_CONTRACT.md \
  planning/phases/C13/C13_2_SOURCE_RECEIPT.json \
  planning/phases/C13/C13_SOURCE_RECEIPT.json \
  tools/verify_c13_checkpoint_reconstruction.py \
  tests/test_c13_authoritative_books.py
git commit -m "feat: add C13-2 checkpoint reconstruction evidence"
```

### Task 7: Reconcile derived files and run every exit gate

**Files:**
- Modify: `MANIFEST.json`
- Verify: all changed files and repository gates

- [ ] **Step 1: Regenerate and check derived artifacts.**

```bash
python3 tools/regenerate_derived.py --root . --json
python3 tools/regenerate_derived.py --root . --check --json
```

- [ ] **Step 2: Run focused C13 validators.**

```bash
PYTHONPATH=src python3 tools/verify_c13_contract.py --root . --json
PYTHONPATH=src python3 tools/verify_c13_execution_safety.py --root . --json
PYTHONPATH=src python3 tools/verify_c13_checkpoint_reconstruction.py --root . --json
```

- [ ] **Step 3: Run the complete repository gates.**

```bash
python3 tools/validate_repository.py --root . --json
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 tools/verify_foundation.py --json
PYTHONPATH=src python3 tools/verify_data_foundation.py --json
PYTHONPATH=src python3 tools/verify_market_data.py --json
PYTHONPATH=src python3 tools/verify_feature_foundation.py --json
PYTHONPATH=src python3 tools/verify_research_governance.py --json
PYTHONPATH=src python3 tools/verify_execution_calibration.py --json
PYTHONPATH=src python3 tools/verify_architecture_reconciliation.py --root . --json
PYTHONPATH=src python3 tools/verify_requirements_reconciliation.py --json
PYTHONPATH=src python3 tools/verify_proof_binding.py --json
PYTHONPATH=src python3 tools/verify_proof_engine.py --json
python3 -m compileall -q src tools tests
git diff --check
```

- [ ] **Step 4: Build and verify the deterministic pack.**

```bash
python3 tools/build_claude_pack.py --root . \
  --output /tmp/MARKET-OS-CODEX-PACK-c13-2.zip --verify --allow-dirty --json
```

Expected: deterministic rebuild match, all source validators green, and
locks unchanged.

- [ ] **Step 5: Commit only derived-file changes.**

```bash
git add MANIFEST.json
git commit -m "chore: reconcile C13-2 derived manifest"
```

### Task 8: Review, push, merge, and clean up

**Files:**
- Verify: `git diff c52370f..HEAD`, GitHub checks, worktrees

- [ ] **Step 1: Inspect the complete diff and worktree.**

```bash
git diff --stat c52370f..HEAD
git diff --check c52370f..HEAD
git status --short --branch
```

Stage only confirmed C13-2 paths; do not use `git add -A`.

- [ ] **Step 2: Request one independent read-only review.**

The reviewer must check checkpoint witness authenticity, bootstrap/legacy
behavior, snapshot invariants, rollback ordering, source receipts, manifest
integrity, and unchanged authority locks. Close the reviewer immediately
after its verdict; never have more than one active reviewer.

- [ ] **Step 3: Push a dedicated branch and open a non-draft PR.**

Target branch: `codex/pr14-pr20-reconciliation-proof`. Include the exact
local commands, validator summaries, hard-lock state, and remaining C13-C16
gaps in the PR body.

- [ ] **Step 4: Wait for exact-head GitHub checks.**

Merge only when the exact head is green and mergeable. Use an expected head
SHA and merge method `merge`; do not force-push or merge into `main`.

- [ ] **Step 5: Refresh and clean temporary worktrees.**

Fast-forward the integration ref, verify its merged SHA and status, remove
only the temporary C13-2 worktree and any detached diagnosis worktree, and
leave the user’s existing inspection worktree untouched.

- [ ] **Step 6: Final verification and handoff.**

Report the merged SHA, exact-head CI conclusions, test count, validator JSON
summaries, deterministic pack hash, changed files, remaining C13-C16 open
gaps, and all preserved locks. Do not call the MarketOS implementation
complete.
