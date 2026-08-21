# C13-1 Pre-Trade Execution Safety Design

## Status

This design is an architectural, non-live extension of the verified C13-0
slice. The first critical design gate returned NO-GO and required the three
trust-boundary corrections specified below; this document is the corrected
design submitted for the final implementation gate. A later gate identified
two capabilities that are deliberately excluded rather than overstated:
cryptographic proof against simultaneous rewriting of both a ledger and its
external witness, and restart reconstruction of a non-empty C13 book. It does
not complete C13 or authorize a broker, capital, live trading, profitability,
or promotion. The final critical gate returned: `GO — bounded non-live C13-1
only; C13 remains incomplete`.

## Goal

Route every paper/shadow `PaperBroker` mutation through one provenance-bound
pre-trade envelope that derives the risk context from the same authoritative
book and market snapshot used by the final veto, rejects missing or stale
evidence, and prevents a concurrent state change between evaluation and fill.

## Chosen architecture

`C13PreTradeEnvelope` in `src/marketos/execution_safety.py` is the only public
paper/shadow submission seam. It owns no broker credentials and has no external
order route. It binds one opaque broker capability and one ledger transaction
owner. It is constructed with one `PaperBroker`, one
`AuthoritativePortfolioBook`, and its exact `DurableLedger`; construction fails
if those identities do not match.

The envelope serializes the broker state lock and the durable-ledger execution
lock in a fixed order. Under those locks it captures one portfolio snapshot and
one immutable aggregate market view: the execution quote plus every mark used
to calculate current gross exposure. It reconciles the portfolio through the
provenance-bound C13-0 gate, asks the broker's private preparation seam to
derive the visible-liquidity bound, cash, position, exposure, data-age and
clock context, including freshness evidence for every contributing mark, and
then opens a SQLite `BEGIN IMMEDIATE` transaction that
compares the expected ledger head before any fill append. The market head is
rechecked while the broker lock is held. A changed ledger or market head
returns a deterministic `NO_TRADE` report without changing the portfolio,
market cache, report cache, or idempotency state.

`DurableLedger` gains a re-entrant execution lock used by all book writes and
reads that participate in the envelope plus an atomic execution transaction.
Book appends and the post-fill checkpoint join that transaction; the expected
head comparison occurs inside the same `BEGIN IMMEDIATE` boundary. The private
mutation seam also requires the active owner-bound transaction, not merely the
capability. A rollback
restores the in-memory authoritative book snapshot and checkpoint list. The
existing `.anchor.json` remains an independent witness and must match the
committed SQLite head exactly. The transaction records the previous sidecar
bytes, replaces and fsyncs the new sidecar before commit, and restores and
fsyncs the previous bytes if the transaction rolls back. A crash or write
failure that leaves the sidecar missing or mismatched causes reopen to fail
closed; there is no automatic repair from a possibly stale database. This
preserves the safety property without claiming proof against an attacker who
rewrites both the database and its witness.
`PaperBroker` gains a re-entrant state lock around market and report state. The
public `PaperBroker.submit` path is removed as an authority seam; direct
callers receive a fail-closed invariant error and must use the envelope. The
private commit seam requires an opaque capability and the bound active
transaction owner, so a fabricated prepared object, gate result, or direct
capability call cannot become a second mutation path. Rejection and shadow
reports also perform the expected-head transaction before caching; a race is
returned as an uncached deterministic `NO_TRADE`.

The existing Risk Kernel remains deterministic, but its caller-supplied
`books_reconciled` context field is removed. Book authority belongs only to
the C13 reconciliation gate. `RiskContext` carries the portfolio snapshot,
ledger-head, and aggregate market-view hashes. The resulting risk decision and
C13 gate fingerprints bind those hashes to the intent and are included in
every execution report together with the source ledger and market heads.

After an inserted paper fill, the envelope writes a checkpoint for the same
authoritative book inside the same ledger transaction before returning. This
keeps the next submission reconcilable without asking callers to fabricate or
manually pass a checkpoint. If checkpoint persistence or any pre-commit step
fails, the database transaction, prior sidecar bytes, in-memory book, market
cache, report cache, and idempotency state are left unchanged; no false allow
is returned. If a process crashes after the database commit but before a
sidecar write can be proven complete, the next open fails closed and requires
an independent recovery procedure.

## Public interfaces

```python
class C13PreTradeEnvelope:
    def __init__(
        self,
        *,
        broker: PaperBroker,
        book: AuthoritativePortfolioBook,
        ledger: DurableLedger,
    ) -> None: ...

    def submit(
        self,
        intent: OrderIntent,
        *,
        now_ns: int,
        clock_quality: ClockQuality,
    ) -> ExecutionReport: ...
```

The envelope does not accept a risk decision, risk context, reconciliation,
book boolean, liquidity override, portfolio snapshot, or execution mode
override. The mode is read from the immutable intent and only `PAPER` and
`SHADOW` can pass the C13 gate. Visible bid/ask quantity in the authoritative
market snapshot is the only admitted liquidity bound; malformed or absent
market state fails closed before mutation. It also refuses a
`DurableLedger.authoritative_book()` binding when the ledger is non-empty;
restart reconstruction from a persisted checkpoint is a later C13 slice, not
an implicit capability of this envelope.

`ExecutionReport` records the C13 gate fingerprint, authoritative ledger head,
portfolio snapshot hash, and aggregate market-view fingerprint in addition to
the existing risk decision and report fingerprint. Existing report states
remain unchanged: rejected risk, cancelled non-marketable/no-liquidity, paper
fills, bounded partial fills, and shadow no-execution.

## Trust and failure boundaries

- A non-authoritative or unrelated portfolio/ledger pair is rejected at
  envelope construction.
- Forged, divergent, stale, advanced-head, or malformed reconciliation is a
  final `NO_TRADE` and cannot be supplied by the caller.
- The risk context is derived from the captured authoritative portfolio and
  complete market view under the same locks as the commit; every mark used for
  gross exposure is included in the aggregate market-view hash.
- Unknown, malformed, crossed, or missing market/liquidity state cannot produce
  a fill. Zero visible quantity remains an explicit no-liquidity cancellation.
- A ledger-head or market-head change before commit produces `NO_TRADE` with
  `EXECUTION_STATE_CHANGED` and no portfolio, database, market, report-cache,
  or idempotency mutation. The ledger expected-head comparison and fill append
  share one SQLite write transaction.
- A missing or mismatched sidecar witness is a hard integrity failure. The
  implementation does not automatically accept or rewrite an older prefix,
  and it does not claim detection if both the SQLite history and its external
  witness are maliciously rewritten together.
- A reopened non-empty ledger cannot be promoted to an authoritative book by
  this slice; it remains explicitly blocked by `BOOK_RECONSTRUCTION_REQUIRED`.
- Idempotency remains keyed by the existing intent idempotency key; a
  conflicting payload remains a `DuplicateConflict`.
- No live enum, broker adapter, OMS/EMS, cancel-all registry, optimizer,
  multi-asset rebalance, FX, tax lot, corporate action, production accounting,
  secret, chaos, DR, C14, C15, or C16 behavior is introduced.

## Acceptance matrix

| Requirement/risk | Observable result | Evidence |
| --- | --- | --- |
| `AUD-RSK-001` | A valid reconciled paper intent is deterministic; every malformed or vetoed input is `NO_TRADE`. | Focused envelope tests and C13 gate tests |
| `AUD-RSK-002` | Cash, gross exposure, position, freshness, clock, instrument, and visible-liquidity constraints bound one intent; unknown inputs fail closed. | Boundary and negative tests |
| `AUD-RSK-004` | Direct broker submit is forbidden; stale/divergent state and a changed head cannot mutate the book. | API-seam, divergence, and deterministic TOCTOU tests |
| `AUD-RSK-005` | Filled paper trades use the exact authoritative ledger and checkpoint source. | Durable-ledger integration tests |
| `AUD-RSK-009` | Report fingerprints retain risk, C13 gate, ledger-head, and market-head evidence. | Fingerprint tamper/regression tests |
| Hard locks | `HARD_LOCKED`, `UNPROVEN`, `promotion_allowed=false`, and `phase_complete=false` remain unchanged. | C13 validator, repository validator, Proof Engine |

The focused race tests use two `DurableLedger` connections to the same SQLite
path to prove that a competing writer committed before the envelope's
transaction is detected and that a writer attempting to commit after
`BEGIN IMMEDIATE` cannot interleave with the fill. Failure injection covers
ledger append, checkpoint append, sidecar replacement, sidecar restoration,
and transaction commit. Restart verification proves that a successful
transaction retains an equal witness, a rolled-back transaction retains the
old witness, and a missing/mismatched witness fails closed; no restart
reconstruction claim is made.

## Explicit exclusions

This slice does not implement a multi-asset optimizer or solver, broker/OMS/EMS
adapters, external submission, pending-order cancellation, kill-switch
orchestration, FX/tax-lot/corporate-action settlement, production accounting,
secrets or authentication, chaos or disaster-recovery drills, C14 cockpit
operations, C15 qualification, C16 packaging, or any production/live claim.

## Verification and rollback

The focused suite is `tests/test_c13_execution_safety.py` plus affected paper,
risk, replay and C13 tests. The full repository suite, C13 validator,
repository validator, Proof Engine, Proof Binding, derived-file check,
compile check, and `git diff --check` are required before integration.

Rollback is limited to reverting the C13-1 commits from the feature branch.
The C13-0 evidence and all authority locks remain intact; no database or
external service is modified by the implementation or its tests.
