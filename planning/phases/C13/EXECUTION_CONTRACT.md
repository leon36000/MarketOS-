# C13-0 — Authoritative Books and Risk Veto Execution Contract

## Objective

Implement the first executable C13 slice: a durable, reconstructible and
tamper-evident paper/shadow ledger, a persisted portfolio checkpoint and a
fail-closed reconciliation/risk veto boundary.

This is a verified partial slice. It does not complete C13 and it does not
authorize a broker, capital, live trading or profitability claims.

## Scope

- SQLite WAL persistence with `synchronous = FULL` for local paper/shadow
  journal and portfolio checkpoints.
- Canonical JSON and SHA-256 validation for every persisted record and chain.
- Idempotent stable IDs, conflicting redelivery rejection and atomic batches.
- Exact double-entry replay through the existing `Ledger`.
- `PortfolioSnapshot` checkpoint/reconciliation with deterministic divergence
  reasons.
- `C13RiskGate` accepting only an intact `RiskDecision`, a reconciled book and
  `PAPER` or `SHADOW` mode.

## Out of Scope

- Broker adapters, OMS/EMS, external order submission, cancel-all and kill
  switch routing.
- Portfolio optimization, FX, tax lots, corporate-action settlement and
  production accounting policy.
- Chaos engineering, disaster-recovery drills, secret-vault integration,
  authentication and C14 cockpit operations.
- Resolution of the 108 canonical versus 119/111 memory discrepancy.
- Any transition of `HARD_LOCKED`, `UNPROVEN` or `promotion_allowed = false`.

## Required Files

- `src/marketos/authoritative_books.py`
- `tests/test_c13_authoritative_books.py`
- `tools/verify_c13_contract.py`
- `docs/implementation/C13_AUTHORITATIVE_BOOKS_RISK_VETO.md`
- `planning/phases/C13/C13_DECISIONS.json`
- `planning/phases/C13/C13_REQUIREMENT_CLOSURE.json`

## Interfaces

`DurableLedger(path)` preserves the book-facing operations `post`,
`post_many`, `reverse`, `entries`, `balance` and `sha256`, and adds
`checkpoint(checkpoint_id, book, captured_at_ns=...)`, `latest_checkpoint`,
`verify` and `close`. The checkpoint derives its snapshot from a
`PortfolioBook` bound to the durable ledger; a caller-supplied snapshot is not
accepted as authoritative. A second append-only ledger-head chain detects
tail truncation.

`reconcile_book(ledger, snapshot)` returns `BookReconciliation` with status
`RECONCILED` or `DIVERGENT`, both source fingerprints and stable reasons. Its
expected digest includes the status, and reason order is
`JOURNAL_INTEGRITY_FAILURE`, `MISSING_BOOK_CHECKPOINT`,
`BOOK_LEDGER_HASH_MISMATCH`, `CHECKPOINT_STALE`,
`BOOK_SNAPSHOT_MISMATCH`. A reconciled result is additionally bound to an
opaque provenance capability for the source ledger head and checkpoint;
`C13RiskGate` re-verifies those live bindings and rejects fabricated or stale
reconciliation objects.

`C13RiskGate.evaluate(decision, reconciliation, mode)` returns
`C13GateDecision`. It returns `ALLOW` only for an intact upstream allow,
reconciled books, a valid `PAPER`/`SHADOW` mode and the unchanged hard lock.
Every other input returns `NO_TRADE`.

## TDD Sequence

1. Prove close/reopen persistence with a real SQLite file and exact cash
   balance.
2. Prove idempotent duplicate handling, conflict rejection, atomic batches,
   reversal persistence and append-only SQL triggers.
3. Prove record and chain tamper detection.
4. Prove checkpoint reconstruction and divergence reasons.
5. Prove a reconciled paper allow and divergent/upstream/unknown-mode vetoes.
6. Prove the standalone validator reports a verified but non-promotable slice.

## Verification Commands

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books -v
python3 tools/verify_c13_contract.py --root . --json
python3 tools/validate_repository.py --root . --json
python3 tools/verify_proof_engine.py --root . --json
python3 tools/verify_proof_binding.py --root . --json
python3 tools/regenerate_derived.py --root . --check --json
python3 -m compileall -q src tools tests
git diff --check
```

## Failure Injection

- Mutate a journal record JSON, record digest, sequence or previous digest;
  opening or verifying the ledger must fail closed.
- Attempt SQL update/delete; append-only triggers must reject both operations.
- Redeliver a stable ID with different content; `DuplicateConflict` must be
  raised without changing the stored state.
- Change a checkpoint snapshot or append a later ledger entry; reconciliation
  must become `DIVERGENT` and the risk gate must return `NO_TRADE`.
- Pass an upstream veto or a string mode outside `PAPER`/`SHADOW`; the gate
  must remain `NO_TRADE`.

## Exit Gate

This slice is verified only when all focused tests, the standalone validator,
repository validation, Proof Engine, Proof Binding, derived-file check,
compile check and diff check pass. The report must preserve
`phase_complete = false`, `promotion_allowed = false`,
`live_trading_state = HARD_LOCKED` and `profitability_state = UNPROVEN`.

The broader `C13_RUNTIME_CONTRACTS` gap remains open because the optimizer,
broker/OMS/EMS, full accounting, security/DR and their independent gates are
outside this slice.

## Rollback

Remove the C13-0 commits from the feature branch only if the exit gate fails;
preserve any generated SQLite fixture outside the repository, do not rewrite
the canonical requirements or authority history, and keep all live and
promotion locks unchanged.
