# C13-2 Checkpoint-Authenticated Restart Reconstruction

## Status and boundary

This specification defines the next bounded C13 runtime slice. It permits
paper/shadow restart restoration only from a checkpoint whose authenticity is
bound to the durable witness and whose snapshot describes the current
verified ledger head.

It does not complete C13, authorize external order submission, select a
broker, unlock live trading, prove profitability, or close C14-C16.

The authority boundary remains:

```text
live_trading_state = HARD_LOCKED
profitability_state = UNPROVEN
phase_complete = false
promotion_allowed = false
external_order_submission = FORBIDDEN
```

## Problem and threat model

The current C13-0/C13-1 runtime can persist a portfolio checkpoint, but a
reopened non-empty ledger cannot safely publish an authoritative book. The
journal postings do not retain enough trade quantity and price semantics to
reconstruct average cost independently. The existing sidecar authenticates
the ledger head but not the checkpoint chain.

The slice protects against:

- a SQLite-only checkpoint rewrite, including a rewrite that recomputes the
  checkpoint row digest;
- a checkpoint row inserted, removed, reordered, or chained outside the
  append-only sequence;
- a checkpoint whose snapshot is stale, temporally invalid relative to the
  ledger, malformed, duplicated, or inconsistent with derived cash;
- a legacy sidecar being silently upgraded into a trusted checkpoint witness;
- a concurrent ledger advance during book restoration.

An actor who can rewrite both the SQLite database and the independent witness
sidecar in a coordinated operation remains out of scope, as it was in
C13-1. The runtime must fail closed rather than attempt automatic repair.

## Chosen approach

The sidecar becomes a versioned witness for two append-only heads:

1. the ledger head already authenticated by C13-0/C13-1; and
2. the latest checkpoint row, represented by its sequence and record digest.

The sidecar payload for a new store is:

```json
{
  "anchor_version": "2.0.0",
  "head_sequence": 3,
  "ledger_entry_count": 3,
  "head_record_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "head_ledger_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "checkpoint_sequence": 1,
  "checkpoint_record_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

The `anchor_sha256` continues to cover the complete payload. A store with no
checkpoint uses `checkpoint_sequence = 0` and an empty checkpoint digest.
Ledger writes retain the checkpoint witness, even when the checkpoint becomes
stale; restoration then rejects it because its snapshot ledger digest no
longer equals the current ledger head. A successful checkpoint write updates
both the SQLite checkpoint chain and the sidecar witness under the existing
durable transaction/rollback boundary. A sidecar failure is a hard failure;
the system never repairs or silently promotes an un-witnessed checkpoint.

## Restart restoration contract

`DurableLedger` loading follows this order:

1. Verify the append-only ledger rows, ledger heads, and ledger sidecar.
2. Load and verify every checkpoint row, including sequence, canonical JSON,
   row digest, and `previous_sha256` chain.
3. Verify the sidecar checkpoint witness against the actual latest checkpoint
   row, or against the explicit zero-checkpoint marker.
4. When `authoritative_book(base_currency=...)` is requested on a non-empty
   ledger, require a version-2 witness and an actual latest checkpoint.
5. Require the checkpoint snapshot ledger digest to equal the current verified
   ledger digest exactly.
6. Require checkpoint base currency and nested money currencies to agree,
   positions to be canonical, quantities and average costs to be valid, and
   checkpoint cash to equal the ledger-derived cash balance.
7. Restore the snapshot into a private book, recompute its snapshot, and
   publish the book only after the recomputed snapshot equals the checkpoint.

Any failure returns a typed invariant failure and leaves no authoritative
book available. The existing `BOOK_RECONSTRUCTION_REQUIRED` boundary remains
the fail-closed result for stale, missing, legacy, or unauthenticated state.

Legacy version-1 sidecars are readable for existing ledger verification and
external reconciliation, preserving C13-0 compatibility. They cannot be used
to restore a non-empty authoritative book. No legacy sidecar is upgraded
automatically; a future explicit re-baselining operation is outside this
slice.

### Bootstrap and legacy policy

The constructor records whether the database path existed before opening the
SQLite connection. Exactly one case may create a genesis sidecar: a genuinely
new path with no pre-existing database file, no pre-existing sidecar, and zero
ledger/head/checkpoint rows. An existing database whose sidecar is missing is
`JOURNAL_INTEGRITY_FAILURE`, even when the database is empty. A version-1
sidecar remains readable for journal verification and external
reconciliation, but a non-empty authoritative book remains blocked with
`BOOK_CHECKPOINT_WITNESS_REQUIRED`; it is never silently upgraded. A
version-2 sidecar is eligible for restoration only after all checks below
pass.

### Exact snapshot invariants

Before restoration, the checkpoint snapshot must satisfy all of these exact
rules:

- `ledger_sha256` is exactly 64 lowercase hexadecimal characters and equals
  the current verified ledger digest;
- `base_currency`, cash currency, realized-P&L currency and every position
  currency are identical uppercase ISO-style three-letter currency codes;
- positions are sorted by strictly increasing `instrument_id`, contain no
  duplicates, and every instrument identifier is a non-empty trimmed string;
- each quantity is finite and non-negative; a zero quantity has average cost
  exactly zero, while a positive quantity has a finite non-negative average
  cost;
- cash and realized P&L use valid finite integer minor units;
- `captured_at_ns` is a non-negative integer greater than or equal to the
  greatest `occurred_at_ns` in the verified ledger. No wall-clock claim is
  made during restart, so “future” means temporally ahead of the ledger
  evidence, not ahead of the machine clock;
- the snapshot cash equals `ledger.balance(cash_account, base_currency)`;
- after restoration, the recomputed snapshot has canonical ordering and an
  identical digest to the checkpoint snapshot.

Each failed invariant has a stable fail-closed error family beginning with
`BOOK_CHECKPOINT_` or `BOOK_SNAPSHOT_`; no malformed snapshot is partially
published as an authoritative book.

## Files and interfaces

The implementation is limited to:

- `src/marketos/authoritative_books.py`: versioned checkpoint witness,
  snapshot validation, restore gating, and rollback-safe anchor updates;
- `tests/test_c13_authoritative_books.py`: functional and adversarial runtime
  coverage;
- `tools/verify_c13_checkpoint_reconstruction.py`: standalone C13-2 contract
  validator;
- `planning/phases/C13/C13_2_DECISIONS.json`;
- `planning/phases/C13/C13_2_REQUIREMENT_CLOSURE.json`;
- `planning/phases/C13/C13_2_EXECUTION_CONTRACT.md`;
- `docs/implementation/C13_2_CHECKPOINT_AUTHENTICATED_RESTART.md`;
- the C13-2 source receipt and derived `MANIFEST.json`.

The C13-1 contract remains historically accurate for its own slice: its
execution envelope does not invent restart reconstruction. The new C13-2
contract explicitly supersedes only the narrow, checkpoint-authenticated
restoration boundary and preserves all authority locks.

## Required tests and gates

The TDD sequence must prove, in order:

1. a current version-2 checkpoint restores positions, realized P&L and cash;
2. no checkpoint, stale checkpoint and legacy checkpoint remain blocked;
3. a SQLite-only checkpoint rewrite with a recomputed row digest is rejected;
4. checkpoint sequence, chain, canonical shape, currency, cash and snapshot
   ledger-digest tampering are rejected;
5. a missing, stale or malformed sidecar is rejected without repair;
6. a concurrent ledger advance cannot publish a restored book;
7. failed checkpoint/witness replacement leaves the prior state intact;
8. C13-0, C13-1, full repository, repository contract, Proof Engine, Proof
   Binding, derived-file, compile and diff gates remain green.

The standalone C13-2 validator must report a verified partial slice while
returning `phase_complete = false` and `promotion_allowed = false`.

## Rollback and evidence

If any C13-2 gate fails, revert only the C13-2 implementation and evidence
commits. Preserve C13-0/C13-1 receipts and the CI-history fix. Never rewrite
the canonical requirement set or authority locks. The exit report must record
commands, exact commit hashes, validator JSON summaries, remaining open
subgates, and the explicit simultaneous SQLite/witness rewrite exclusion.
