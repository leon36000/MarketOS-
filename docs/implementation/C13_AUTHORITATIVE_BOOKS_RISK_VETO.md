# C13-0 Authoritative Books and Risk Veto

This document describes the verified first C13 runtime slice. It is a partial
implementation contract, not a claim that C13 or the MarketOS software system
is complete.

## Runtime surface

`marketos.authoritative_books.DurableLedger` wraps the existing exact
double-entry `Ledger` and persists canonical journal entries in SQLite. The
database is configured for WAL and full synchronous writes. Each row contains
an arrival sequence, stable entry ID, canonical record, record digest and
previous-record digest. A second append-only head chain anchors the expected
tail, and a durable sidecar anchor must match that head. SQL update/delete
triggers enforce append-only writes for both chains.

`BookCheckpoint` persists a full `PortfolioSnapshot` and its ledger digest.
`DurableLedger.authoritative_book` creates the only checkpoint-capable book for
a fresh ledger and tracks its mutation head. `checkpoint` derives the snapshot
from that capability; a caller-supplied snapshot or a newly constructed book
cannot become authoritative, and an external ledger writer taints the source.
`reconcile_book` validates both stores, compares the current snapshot with the
latest checkpoint and returns deterministic reasons such as
`BOOK_SNAPSHOT_MISMATCH`, `CHECKPOINT_STALE` and
`JOURNAL_INTEGRITY_FAILURE`. Its expected digest includes reconciliation
status, preventing a forged `DIVERGENT` → `RECONCILED` replacement. The result
also carries an opaque in-process provenance bound to the source ledger head
and checkpoint. `C13RiskGate` re-runs reconciliation from the bound snapshot
before allowing, so a self-consistent fabricated result or a reconciliation
reused after the ledger advances is rejected.

`C13RiskGate` is the final boundary in this slice. It accepts only an intact
`RiskDecision.ALLOW`, a `RECONCILED` book, an actual `PAPER` or `SHADOW`
execution mode and `HARD_LOCKED` state. Any other condition returns
`NO_TRADE`. The module contains no broker submission API.

## Example

```python
from marketos.authoritative_books import C13RiskGate, DurableLedger, reconcile_book
from marketos.portfolio import PortfolioBook

with DurableLedger("paper-books.sqlite") as ledger:
    book = ledger.authoritative_book(base_currency="USD")
    book.fund("funding-1", amount, occurred_at_ns=100)
    snapshot = book.snapshot()
    ledger.checkpoint("checkpoint-1", book, captured_at_ns=200)
    reconciliation = reconcile_book(ledger, snapshot)
    gate = C13RiskGate().evaluate(risk_decision, reconciliation, execution_mode)
```

The caller must treat `NO_TRADE` as terminal for the attempted decision. A
checkpoint is not a broker acknowledgement and cannot authorize an external
order.

## Evidence

```bash
PYTHONPATH=src python3 -m unittest tests.test_c13_authoritative_books -v
python3 tools/verify_c13_contract.py --root . --json
```

The full C13 contract remains open for optimizer constraints, broker/OMS/EMS,
operational kill switches, complete accounting, security/DR and independent
qualification gates.
