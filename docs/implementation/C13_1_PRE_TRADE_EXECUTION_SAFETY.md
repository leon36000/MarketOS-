# C13-1 Pre-Trade Execution Safety

This document records the bounded C13-1 slice. It is a verified partial
implementation, not a claim that C13 or MarketOS is complete.

## Runtime boundary

`C13PreTradeEnvelope` is the only public paper/shadow submission seam. Its
constructor requires the exact `PaperBroker`, `AuthoritativePortfolioBook` and
`DurableLedger` identities and binds an opaque capability to that broker.
The envelope also binds a private transaction owner to the ledger; the broker
mutation primitive requires both that owner and an active owner-bound durable
transaction, so possession of a capability alone cannot create a fill.
`PaperBroker.submit` fails closed with
`PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN`.

The envelope derives the portfolio snapshot, ledger head, execution quote and
every mark used for current gross exposure, including each evidence timestamp.
`RiskContext` carries the three source fingerprints and validates freshness and
future-data constraints for every contributing quote/mark; no caller can
provide a reconciliation boolean, risk decision, snapshot, liquidity result or
execution mode override.

## Atomic commit

For `PAPER`, the envelope rechecks the captured view, requires an unchanged
ledger head inside `BEGIN IMMEDIATE`, applies the fill and appends the
authoritative book checkpoint in the same SQLite transaction. Rejection and
shadow reports use the same expected-head transaction before entering the
idempotency cache. A changed head returns a deterministic uncached
`NO_TRADE`/`EXECUTION_STATE_CHANGED` result.

The durable sidecar is an exact independent witness: replacement is fsynced
before commit, and rollback independently attempts restoration of both the
prior bytes and the in-memory authoritative book. Checkpoint refresh happens
before SQLite `COMMIT`; any failure therefore rolls back the database, book,
checkpoint list and witness bytes. A missing or mismatched sidecar is a veto;
no automatic repair is attempted.

Reports and market/idempotency caches are finalized only after the transaction
commits. Any failure after an in-memory book mutation restores the book,
ledger, checkpoint list and witness bytes. A race that changes the expected
head is not cached as a completed order.

`SHADOW` may pass the deterministic gate but produces no fill or book
mutation. Both modes remain non-live and the hard lock remains
`HARD_LOCKED`.

## Explicit exclusions

- A reopened non-empty ledger remains blocked with
  `BOOK_RECONSTRUCTION_REQUIRED`; this slice provides no restart
  reconstruction.
- Protection against an actor rewriting both SQLite and the witness sidecar
  simultaneously is out of scope; the independent witness protects against
  ordinary ordering, rollback and single-source mismatch failures.
- Broker adapters, OMS/EMS, external routes, cancel-all/kill orchestration,
  portfolio optimization, FX/tax lots/corporate actions, production
  accounting, secrets/authentication, chaos/DR and C14-C16 remain open.

## Evidence

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_execution_safety -v
python3 tools/verify_c13_execution_safety.py --root . --json
```

The acceptance evidence covers paper allow, direct-submit veto, expected-head
races on allow/rejection/shadow paths, sidecar mismatch and write-failure
rollback, reconstruction block, quote/liquidity vetoes, stolen-capability
transaction closure, stale aggregate marks, idempotency/cache finalization,
rollback restoration and replay-path independence.
