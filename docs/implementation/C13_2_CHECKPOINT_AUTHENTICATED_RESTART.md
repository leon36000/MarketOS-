# C13-2 — Authenticated Checkpoint Restart

This is a verified, bounded C13-2 slice. It restores a paper/shadow
authoritative portfolio only from the latest checkpoint whose snapshot is
bound to the current journal head and whose record is witnessed by the v2
sidecar anchor. It does not complete C13, select a broker, authorize capital,
or change any authority lock.

## Boundary

- `live_trading_state` remains `HARD_LOCKED`.
- `profitability_state` remains `UNPROVEN`.
- `promotion_allowed` remains `false`.
- A current-head checkpoint is the only restart reconstruction source.
- Journal replay is still used to authenticate the ledger and to derive the
  cash balance for a checkpoint's exact ledger prefix; it is not used to infer
  trade positions or realized P&L.

## Witness and bootstrap rules

The v2 sidecar records the journal head plus the checkpoint sequence and
transitive checkpoint record digest. Each v2 checkpoint digest commits both
its canonical record and its predecessor digest, so a historical chain
rewrite changes the witnessed current-head digest. A fresh path may create a v2 genesis anchor only when the path
did not exist and all three persisted tables are empty. An existing database
without its sidecar fails with `JOURNAL_INTEGRITY_FAILURE`. A legacy v1
sidecar may be opened for audit and reconciliation, but a non-empty store
cannot restore or mutate an authoritative book until it has an independently
approved v2 baseline; the runtime never upgrades it automatically.

Restoration runs under a SQLite `BEGIN IMMEDIATE` writer lock from the fresh
head read through snapshot validation and authoritative-book publication. Any
concurrent writer therefore waits until the restored book has been published,
and the head is checked again before commit. Any journal-head mismatch remains a journal integrity failure. A checkpoint
record rewrite that preserves its SQLite row digest but disagrees with the
sidecar is `BOOK_CHECKPOINT_WITNESS_FAILURE`.

## Snapshot invariants

Checkpoint snapshots require a three-letter uppercase currency, lowercase
64-character SHA-256 digest, matching cash and realized-P&L currencies,
strictly increasing unique trimmed instrument IDs, finite non-negative
quantities, and finite non-negative average costs. A zero quantity requires a
zero average cost. Cash must equal the derived ledger cash at the snapshot's
ledger prefix. The capture time must be at least the greatest journal event
time in that prefix. The restored snapshot must equal the checkpoint exactly
after loading.

## Failure posture

There is no automatic repair, sidecar rebaselining, or position inference.
Anchor writes remain atomic and rollback-safe inside regular checkpoints and
the authorized execution transaction. Any failed witness, malformed snapshot,
stale checkpoint, or rollback cleanup failure fails closed and preserves the
existing C13 locks.

## Evidence

The focused tests in `tests/test_c13_authoritative_books.py` cover restart,
bootstrap, legacy refusal, checkpoint rewrite detection and capture-time
validation. `tools/verify_c13_checkpoint_reconstruction.py` repeats the
critical scenarios independently and reports this slice as verified but
non-promotable.
