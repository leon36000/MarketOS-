# C13-1 Pre-Trade Execution Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every paper/shadow order through one provenance-bound, transaction-safe pre-trade envelope without changing any live or promotion lock.

**Architecture:** Add `C13PreTradeEnvelope` as the only public mutation seam around `PaperBroker`. It derives one immutable portfolio/market evidence set, including every mark timestamp used for gross exposure, invokes the existing deterministic Risk Kernel and C13-0 reconciliation veto, then commits a fill and checkpoint inside an expected-head SQLite transaction owned by the envelope. The existing sidecar remains an exact independent witness; mismatch or missing data fails closed, and non-empty ledger reconstruction remains explicitly blocked.

**Tech Stack:** Python 3.12, standard library `dataclasses`, `threading.RLock`, `sqlite3` WAL/`BEGIN IMMEDIATE`, SHA-256 canonical fingerprints, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-20-c13-1-pre-trade-execution-safety-design.md`

## Global Constraints

- `live_trading_state` stays exactly `HARD_LOCKED`.
- `profitability_state` stays exactly `UNPROVEN`.
- `promotion_allowed` and `phase_complete` stay `false`.
- Only `ExecutionMode.PAPER` and `ExecutionMode.SHADOW` are accepted.
- `PaperBroker.submit` is fail-closed; all runtime callers use `C13PreTradeEnvelope.submit`.
- No broker adapter, OMS/EMS, external order route, optimizer, cancel-all registry, FX, tax-lot, corporate-action, secrets, C14, C15, or C16 behavior is added.
- `DurableLedger.authoritative_book()` continues to reject a non-empty ledger with `BOOK_RECONSTRUCTION_REQUIRED`.
- No third-party dependency is introduced; no canonical requirement count or phase status is promoted.
- Every production behavior change follows a witnessed RED → GREEN → REFACTOR cycle.
- Changes stay on `codex/c13-authoritative-books-risk-veto`; integration is performed only after fresh gates pass.

---

### Task 1: Add an atomic durable-ledger execution boundary

**Files:**
- Modify: `src/marketos/errors.py`
- Modify: `src/marketos/authoritative_books.py`
- Create: `tests/test_c13_execution_safety.py`
- Modify: `tests/test_c13_authoritative_books.py`

**Interfaces:**
- Produces `ExecutionStateChanged(InvariantViolation)` for an expected-head mismatch.
- Produces `DurableLedger.execution_transaction(expected_ledger_sha256, owner=bound_owner)` as a context manager; the broker mutation primitive requires that owner and an active transaction.
- Keeps `AuthoritativePortfolioBook` fresh-only; no reopen reconstruction API is produced.

- [ ] **Step 1: Write the failing persistence and race tests.** Add tests that create two `DurableLedger` objects for one temporary SQLite path and assert that `execution_transaction` rejects a stale expected head, that a fill inside a successful transaction persists, and that a sidecar mismatch or missing sidecar rejects reopen. Add a rollback test that raises after a book append and asserts the original entry list, snapshot, checkpoint list, and sidecar bytes remain unchanged.

```python
with DurableLedger(path) as first, DurableLedger(path) as second:
    expected = first.sha256()
    first.post(entry("outside"))
    with self.assertRaises(ExecutionStateChanged):
        with second.execution_transaction(expected):
            self.fail("stale transaction must not enter commit body")
```

- [ ] **Step 2: Run the focused tests and confirm the expected RED state.**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety tests.test_c13_authoritative_books -v
```

Expected: failure because `ExecutionStateChanged` and `execution_transaction` do not yet exist, not an import or fixture error.

- [ ] **Step 3: Implement the smallest transaction boundary.** Add a re-entrant ledger lock and an active-transaction marker. `execution_transaction` must execute `BEGIN IMMEDIATE`, read/verify the current ledger, compare its SHA-256 with the expected head inside the transaction, yield to the authorized book operation, commit only after the checkpoint and sidecar write succeed, and roll back on every exception. Capture previous sidecar bytes before replacement; restore and fsync them after rollback. Do not automatically repair a missing or historical-prefix sidecar. Make `post`, `post_many`, `checkpoint`, `verify`, `entries`, `balance`, and `sha256` use the lock; when called inside the execution transaction they must not open a nested SQLite transaction.

- [ ] **Step 4: Add the in-memory rollback seam.** Add a private `AuthoritativePortfolioBook._restore_snapshot(snapshot)` used only by the envelope's transaction exception path. It restores positions, realized PnL, and the tracked ledger head after SQLite rollback and rejects a snapshot from another currency or ledger.

- [ ] **Step 5: Run the focused tests GREEN and preserve C13-0 behavior.**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety tests.test_c13_authoritative_books -v
```

Expected: all focused persistence, sidecar, and existing C13-0 tests pass.

- [ ] **Step 6: Commit the transaction boundary.**

```bash
git add src/marketos/errors.py src/marketos/authoritative_books.py tests/test_c13_execution_safety.py tests/test_c13_authoritative_books.py
git commit -m "feat: add atomic C13 execution transaction"
```

### Task 2: Bind risk and market evidence to one immutable preparation

**Files:**
- Modify: `src/marketos/risk.py`
- Modify: `src/marketos/paper.py`
- Modify: `src/marketos/authoritative_books.py`
- Modify: `tests/test_risk.py`
- Modify: `tests/test_c13_authoritative_books.py`
- Test: `tests/test_c13_execution_safety.py`

**Interfaces:**
- `RiskContext` carries `portfolio_snapshot_sha256`, `ledger_head_sha256`, and `market_view_sha256`; it no longer carries `books_reconciled`.
- `MarketSnapshot.sha256()` returns its canonical fingerprint.
- A frozen `MarketView` contains the intent execution quote and every current-position mark used by gross exposure.
- `PaperBroker` exposes only private `_prepare`, `_commit_authorized`, and `_finalize_pending` seams to the envelope.
- `ExecutionReport` carries C13 gate, portfolio, ledger, and market-view fingerprints.
- `C13GateDecision` carries the same source binding hashes when the envelope invokes `C13RiskGate`.

- [ ] **Step 1: Write failing evidence-binding tests.** Assert that a risk decision changes when any source hash changes, that a held position's mark is included in the aggregate market-view hash, that direct `PaperBroker.submit` raises `PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN`, and that a forged private capability cannot commit a fill.

```python
tampered = replace(context, market_view_sha256="f" * 64)
self.assertNotEqual(
    RiskKernel(limits).evaluate(intent, context).context_sha256,
    RiskKernel(limits).evaluate(intent, tampered).context_sha256,
)
```

- [ ] **Step 2: Run the evidence tests RED.**

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety tests.test_risk -v
```

Expected: failure because the source hash fields, market view, direct-submit guard, and private preparation seam are absent.

- [ ] **Step 3: Remove the reconciliation boolean and add source hashes.** Update `RiskContext` validation/canonicalization and `RiskKernel.evaluate`; migrate every constructor to provide literal or independently derived 64-character hashes. Preserve all existing cash, notional, position, freshness, clock, instrument, and mode checks. Extend `C13GateDecision` and `_build_decision` with optional binding hashes so existing C13-0 callers remain compatible while C13-1 requires non-empty matching hashes.

- [ ] **Step 4: Implement complete market preparation.** Add the frozen market-view value and canonical hash. Under a broker `RLock`, capture the portfolio snapshot, execution quote, all marks required by `_gross_notional`, and the derived execution price/fee. Build `RiskContext` from that exact snapshot/view and return a private prepared object containing the intent hash, portfolio hash, ledger head, aggregate market hash, decision, and expected execution snapshot.

- [ ] **Step 5: Refactor report creation without changing public states.** Add report fields for the C13 gate hash, portfolio snapshot hash, ledger head, and market view. Ensure the report digest includes every field. Do not update the market cache or report/idempotency cache until the transaction has committed.

- [ ] **Step 6: Run GREEN and the neighboring suites.**

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety tests.test_risk tests.test_c13_authoritative_books -v
```

- [ ] **Step 7: Commit the evidence-bound preparation.**

```bash
git add src/marketos/risk.py src/marketos/paper.py src/marketos/authoritative_books.py tests/test_risk.py tests/test_c13_authoritative_books.py tests/test_c13_execution_safety.py
git commit -m "feat: bind C13 risk preparation to source heads"
```

### Task 3: Implement the envelope-only paper/shadow mutation path

**Files:**
- Create: `src/marketos/execution_safety.py`
- Modify: `src/marketos/paper.py`
- Modify: `src/marketos/authoritative_books.py`
- Test: `tests/test_c13_execution_safety.py`

**Interfaces:**
- `C13PreTradeEnvelope(broker, book, ledger)` rejects unrelated identities and binds one opaque capability to one broker instance.
- `C13PreTradeEnvelope.submit(intent, now_ns, clock_quality)` derives reconciliation and risk state internally; no caller-supplied context, boolean, snapshot, liquidity, decision, or mode override is accepted.

- [ ] **Step 1: Add failing end-to-end envelope tests.** Cover a valid paper fill plus checkpoint, shadow no-fill, divergent checkpoint veto, stale/future quote veto, missing visible liquidity, wrong-currency/unsupported inputs, idempotent retry, conflicting idempotency, forged capability, and direct broker submission. Capture book, ledger, sidecar, market cache, and report-cache fingerprints before a forced transaction failure and assert they are unchanged afterward.

- [ ] **Step 2: Run the envelope tests RED.**

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety -v
```

Expected: failure because `marketos.execution_safety` and the envelope-only path are absent.

- [ ] **Step 3: Implement construction and preparation.** Require `isinstance(book, AuthoritativePortfolioBook)`, `isinstance(ledger, DurableLedger)`, `broker.portfolio is book`, and `book.ledger is ledger`. Acquire broker lock before ledger lock. Capture reconciliation from the live snapshot, call the private broker preparation, and require all captured portfolio/ledger/market hashes to match before the C13 gate.

- [ ] **Step 4: Implement fail-closed gate reports.** Invoke `C13RiskGate` with the prepared source hashes. On any veto, perform an owner-bound expected-head transaction before caching the deterministic no-fill report. On `PAPER`/`SHADOW` allow, enter `execution_transaction(prepared.ledger_head, owner=bound_owner)`. Any transaction head mismatch returns an uncached deterministic `NO_TRADE` with `EXECUTION_STATE_CHANGED` without mutating anything.

- [ ] **Step 5: Implement atomic fill and checkpoint.** Inside the transaction, recheck the market-view hash, call the capability- and transaction-owner-checked private broker commit, append the checkpoint for the resulting authoritative book, refresh checkpoints before commit, and return a pending report. Finalize the market and report caches only after commit under the same broker lock. On pre-commit error, independently restore the captured book snapshot and prior sidecar bytes; cleanup failure taints the book fail-closed.

- [ ] **Step 6: Run GREEN, including mutation checks.** Mutate the prepared object, gate hash, ledger head, market snapshot, and capability in separate tests; each mutation must either fail closed or raise before a fill. Then run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety -v
```

- [ ] **Step 7: Commit the envelope.**

```bash
git add src/marketos/execution_safety.py src/marketos/paper.py src/marketos/authoritative_books.py tests/test_c13_execution_safety.py
git commit -m "feat: enforce C13 envelope-only paper execution"
```

### Task 4: Migrate replay and foundation callers to the sealed seam

**Files:**
- Modify: `src/marketos/replay.py`
- Modify: `tests/test_paper.py`
- Modify: `tests/test_replay.py` only if its public expectations need updated evidence fields
- Modify: `tools/verify_foundation.py`

- [ ] **Step 1: Prepare caller fixtures before migration.** Update the paper/replay/foundation fixtures and their assertions to expect an envelope-backed runtime, with a fresh temporary `DurableLedger`, fresh authoritative book, funded initial checkpoint, and no path in the replay fingerprint. Then replace every direct `PaperBroker.submit` call with `C13PreTradeEnvelope.submit`; replay closes the temporary ledger after computing its result.

- [ ] **Step 2: Run affected tests and record the intended RED/compatibility failures.**

```bash
PYTHONPATH=src python3 -m unittest tests.test_paper tests.test_replay tests.test_foundation_acceptance -v
```

Expected: any failure must be limited to the new envelope API or missing migrated fixture setup; fix the caller/fixture, never restore the forbidden boolean API.

- [ ] **Step 3: Preserve behavior and verify GREEN.** Keep exact paper cash/PnL, partial-fill, idempotency, replay ordering, checkpoint resume, CLI fingerprint, and hard-lock assertions. Run the same command until all affected tests pass.

- [ ] **Step 4: Commit the migration.**

```bash
git add src/marketos/replay.py tests/test_paper.py tests/test_replay.py tools/verify_foundation.py
git commit -m "refactor: route replay and foundation through C13 envelope"
```

### Task 5: Add the C13-1 evidence contract and reconcile derived artifacts

**Files:**
- Create: `tools/verify_c13_execution_safety.py`
- Create: `docs/implementation/C13_1_PRE_TRADE_EXECUTION_SAFETY.md`
- Create: `planning/phases/C13/C13_1_EXECUTION_CONTRACT.md`
- Create: `planning/phases/C13/C13_1_DECISIONS.json`
- Create: `planning/phases/C13/C13_1_REQUIREMENT_CLOSURE.json`
- Modify: `planning/phases/C13/C13_SOURCE_RECEIPT.json`
- Modify: `tests/test_c13_execution_safety.py`
- Regenerate: `MANIFEST.json`

- [ ] **Step 1: Write the failing validator acceptance test.** Assert that the standalone validator reports C13-1 as `VERIFIED_SLICE`, lists `AUD-RSK-001`, `AUD-RSK-002`, `AUD-RSK-004`, `AUD-RSK-005`, and `AUD-RSK-009` as partial only, preserves `phase_complete=false`, `promotion_allowed=false`, `HARD_LOCKED`, `UNPROVEN`, and explicitly records the restart reconstruction and simultaneous database/witness rewrite exclusions.

- [ ] **Step 2: Run the validator test RED.**

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety.C13ExecutionSafetyValidatorTests -v
```

Expected: failure because the C13-1 contract and validator artifacts do not yet exist.

- [ ] **Step 3: Implement the standalone validator and evidence docs.** The validator must create a temporary fresh ledger/book/envelope, exercise a paper allow, direct-submit veto, stale-head veto, sidecar mismatch veto, and non-empty reconstruction veto. It must not write to the repository. The decision/closure docs must describe only the bounded slice and preserve all broader C13 open subgates.

- [ ] **Step 4: Update the C13 source receipt.** Recompute SHA-256 values only for the C13-0 source paths actually changed (`src/marketos/authoritative_books.py`, `tests/test_c13_authoritative_books.py`, and `tools/verify_c13_contract.py`) and recompute `source_tree_sha256`; keep `source_parent_commit` and `slice` unchanged. Run the C13 validator to prove the receipt is internally consistent.

- [ ] **Step 5: Regenerate the manifest and run the focused evidence gate.**

```bash
python3 tools/regenerate_derived.py --root .
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety -v
python3 tools/verify_c13_execution_safety.py --root . --json
python3 tools/verify_c13_contract.py --root . --json
```

- [ ] **Step 6: Commit the evidence slice.**

```bash
git add tools/verify_c13_execution_safety.py docs/implementation/C13_1_PRE_TRADE_EXECUTION_SAFETY.md planning/phases/C13/C13_1_EXECUTION_CONTRACT.md planning/phases/C13/C13_1_DECISIONS.json planning/phases/C13/C13_1_REQUIREMENT_CLOSURE.json planning/phases/C13/C13_SOURCE_RECEIPT.json tests/test_c13_execution_safety.py MANIFEST.json
git commit -m "docs: record C13-1 execution safety evidence"
```

### Task 6: Independent review, full verification, and integration

**Files:**
- Review: all commits after `76d79bc`
- Verify: final feature branch and a clean integration worktree

- [ ] **Step 1: Run the focused and complete checks.**

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety -v
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 tools/verify_c13_execution_safety.py --root . --json
python3 tools/verify_c13_contract.py --root . --json
python3 tools/validate_repository.py --root . --json
python3 tools/verify_proof_engine.py --root . --json
python3 tools/verify_proof_binding.py --root . --json
python3 tools/regenerate_derived.py --root . --check --json
python3 -m compileall -q src tools tests
git diff --check
```

- [ ] **Step 2: Dispatch an independent read-only code review.** Review the complete post-design range against the spec, focusing on two-connection races, sidecar rollback/crash ordering, capability forgery, market-view completeness, direct-call bypasses, and hard locks. Fix Critical/Important findings with a new RED test before any merge.

- [ ] **Step 3: Re-run all checks after review fixes.** Do not rely on the reviewer's summary or a previous run; collect fresh output and record exact counts.

- [ ] **Step 4: Merge only into `codex/pr14-pr20-reconciliation-proof`.** Create a temporary integration worktree from the remote integration branch, merge the feature branch, run the complete verification matrix there, push only that integration branch, verify both remote refs, and remove the temporary worktree. Do not merge into `main`.

- [ ] **Step 5: Close every remaining agent and report the bounded outcome.** State the exact integrated commit, focused/full test counts, validators, hard locks, explicit exclusions, and the remaining C13/C14/C15/C16 gaps. Never report MarketOS or C13 as complete.

## Self-review checklist

- Every C13-1 acceptance row maps to a task and a fresh command.
- No task claims restart reconstruction or protection from simultaneous database/witness rewriting.
- Direct PaperBroker mutation is forbidden before callers are migrated.
- Sidecar rollback and SQLite transaction ordering are tested independently.
- Source receipt and manifest updates are explicit and mechanically checked.
- The plan keeps one write owner per file and serializes integration.
