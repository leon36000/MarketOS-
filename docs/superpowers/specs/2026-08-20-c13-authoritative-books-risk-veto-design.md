# C13-0 Authoritative Books and Risk Veto Design

**Status:** approved for implementation on the isolated Codex branch
`codex/c13-authoritative-books-risk-veto`.

**Scope:** the first executable C13 slice only. This design does not close the
whole C13 phase and does not select a broker, authorize capital, prove
profitability, or enable live trading.

## Goal

Provide a durable, reconstructible and tamper-evident source of truth for
paper/shadow portfolio books, then make risk decisions fail closed whenever
the books cannot be proven reconciled.

## Non-goals

- No production broker adapter, OMS/EMS route or external order submission.
- No portfolio optimizer, tax-lot engine, FX engine or corporate-action
  settlement beyond the existing paper book behavior.
- No change to `live_trading_state = HARD_LOCKED`,
  `profitability_state = UNPROVEN` or `promotion_allowed = false`.
- No attempt to resolve the 108 canonical versus 119/111 observed-memory
  discrepancy.
- No declaration that C13, C14, C15 or C16 is complete.

## Existing boundaries

`marketos.ledger.Ledger` already enforces exact double-entry semantics in
memory. `PortfolioBook` consumes that interface, and `RiskKernel` already
rejects non-paper/non-shadow order modes and stale or unreconciled contexts.
The new slice preserves those APIs and adds a durable adapter plus an explicit
reconciliation/veto boundary around them.

## Design

### Durable ledger adapter

Add `DurableLedger` in a focused C13 runtime module. It wraps the existing
`Ledger` and exposes the same operations used by `PortfolioBook`:

- `post(entry) -> bool`
- `post_many(entries) -> tuple[bool, ...]`
- `reverse(entry_id, reversal_id, occurred_at_ns, description=None)`
- `balance(account, currency)`
- `entries()`
- `sha256()`
- `verify()`
- `close()` and context-manager support

SQLite is used only as a local paper/shadow persistence boundary. The database
uses `journal_mode = WAL` and `synchronous = FULL`. Each row stores its
sequence, stable entry ID, canonical JSON, entry SHA-256 and the previous row
SHA-256. Update and delete triggers make the table append-only.

On open, every row is decoded and replayed through the existing in-memory
`Ledger`. The stored canonical JSON, entry digest, sequence and previous-digest
chain must all match. Any malformed, tampered, missing or out-of-order row
raises a deterministic integrity failure before the ledger can be used.

Identical redelivery of an entry ID is idempotent. Reuse of an entry ID with a
different digest raises `DuplicateConflict`. Batch writes validate and replay
against a clone before one SQLite transaction and one in-memory state swap, so
a failed batch leaves both stores unchanged.

### Reconciliation result

Add an immutable `BookReconciliation` result with:

- `status`: `RECONCILED` or `DIVERGENT`;
- `journal_sha256`, `book_sha256` and `expected_sha256`;
- ordered stable reason codes;
- a deterministic result SHA-256.

The reconciler compares the durable ledger replay with the supplied portfolio
book snapshot and requires the ledger fingerprint referenced by the snapshot
to match the durable ledger fingerprint. A damaged ledger, missing entry,
cash/position mismatch, contradictory stable ID or unverified snapshot is
divergent. Arrival order is preserved separately from `occurred_at_ns`, so a
late event is auditable and never silently reorders history.

### Risk veto

Add a `C13RiskGate` that consumes an existing `RiskDecision`, a
`BookReconciliation` and an execution mode. It returns an immutable gate
decision with `ALLOW` only when all of these hold:

1. the upstream decision is `ALLOW`;
2. reconciliation status is `RECONCILED`;
3. mode is `PAPER` or `SHADOW`;
4. the decision and reconciliation fingerprints are present and valid; and
5. no hard-lock or audit-integrity reason is present.

Every other input returns `NO_TRADE` with stable reason codes. The gate has no
broker dependency and exposes no method that can submit or authorize a live
order.

### Audit behavior

Accepted records retain arrival sequence and event time. Late or out-of-order
records remain visible in the journal. Conflicting redelivery is rejected,
with the conflict represented by a deterministic audit reason returned to the
caller; it never overwrites the accepted record. A reconciliation failure is
itself represented in the gate decision fingerprint, so a caller cannot
silently treat an unavailable audit as approval.

## Error and safety policy

- Integrity or decoding failure: fail closed with `NO_TRADE` at the gate and a
  deterministic domain error at the persistence boundary.
- Stable-ID conflict: reject with `DuplicateConflict`; do not mutate state.
- SQLite transaction failure: roll back and keep the in-memory clone unchanged.
- Any mode other than `PAPER` or `SHADOW`: `NO_TRADE`.
- Any future attempt to weaken the hard locks must fail validation and the
  existing proof engine must remain green only with the locks intact.

## Test contract

The focused test module must prove, using real SQLite files and real domain
objects:

1. persistence survives close/reopen and reconstructs balances and hashes;
2. duplicate redelivery is idempotent and conflicting redelivery is rejected;
3. update/delete attempts are blocked by the append-only database triggers;
4. tampering with canonical JSON, a digest, sequence or chain is detected;
5. failed batch writes do not partially mutate memory or disk;
6. late events preserve arrival order and cannot be mistaken for a clean
   reconciliation;
7. book divergence produces `DIVERGENT` and the risk gate returns `NO_TRADE`;
8. an upstream risk veto remains a veto;
9. live/unknown modes are rejected and the hard locks remain visible; and
10. the standalone C13 validator reports the slice without changing the
    broader phase boundary.

## Verification and integration gates

The slice is eligible for review only after its focused RED/GREEN tests,
full repository tests, repository validator, proof engine, proof binding,
derived-file check, compile check and diff check pass. A fresh independent
`gpt-5.6-sol` review must confirm that the new proof is tied to the current
source state before any merge. The existing C13–C16 open-gap ledger remains
open unless a later, broader phase gate proves otherwise.
