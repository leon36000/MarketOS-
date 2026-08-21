# C13-1 Pre-Trade Execution Safety

This document records the bounded C13-1 slice. It is a verified partial
implementation, not a claim that C13 or MarketOS is complete.

## Runtime boundary

`C13PreTradeEnvelope` is the only public paper/shadow submission seam. Its
constructor requires the exact `PaperBroker`, `AuthoritativePortfolioBook` and
`DurableLedger` identities and binds an opaque capability to that broker.
`PaperBroker.submit` fails closed with
`PAPER_BROKER_DIRECT_SUBMIT_FORBIDDEN`.

The envelope derives the portfolio snapshot, ledger head, execution quote and
every mark used for current gross exposure. `RiskContext` carries the three
source fingerprints; no caller can provide a reconciliation boolean, risk
decision, snapshot, liquidity result or execution mode override.

## Atomic commit

For `PAPER`, the envelope rechecks the captured view, requires an unchanged
ledger head inside `BEGIN IMMEDIATE`, applies the fill and appends the
authoritative book checkpoint in the same SQLite transaction. The durable
sidecar is an exact independent witness: replacement is fsynced before commit,
and rollback restores the prior bytes and fsyncs the directory. A missing or
mismatched sidecar is a veto; no automatic repair is attempted.

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
race, sidecar mismatch, reconstruction block, quote/liquidity vetoes,
capability forgery, idempotency and rollback restoration.
