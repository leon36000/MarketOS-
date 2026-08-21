# C13-1 — Pre-Trade Execution Safety Execution Contract

## Objective

Route every paper/shadow intent through one provenance-bound preparation and
one atomic, expected-head execution transaction while preserving all C13 and
MarketOS locks.

## Scope

- Immutable portfolio, ledger-head and market-view fingerprints in risk
  preparation and execution reports.
- Complete execution quote plus every current-position mark in one market
  view.
- Envelope-only paper/shadow mutation with an opaque broker capability.
- SQLite `BEGIN IMMEDIATE` expected-head check, atomic fill/checkpoint and
  fsynced sidecar rollback witness.
- Post-commit report, market and idempotency cache finalization.
- Replay and foundation migration to the envelope seam.

## Out of Scope

- No restart reconstruction: a reopened non-empty ledger remains
  `BOOK_RECONSTRUCTION_REQUIRED`.
- Simultaneous coordinated rewriting of both SQLite and its witness sidecar is
  out of scope.
- Broker adapters, OMS/EMS, external order submission, cancel-all/kill
  routing, optimizer, FX, tax lots, corporate actions, production accounting,
  secrets/authentication, chaos/DR and C14-C16.
- No promotion, live trading, profitability or full C13 completion claim.

## Required Files

- `src/marketos/execution_safety.py`
- `src/marketos/paper.py`
- `src/marketos/risk.py`
- `src/marketos/authoritative_books.py`
- `tests/test_c13_execution_safety.py`
- `tools/verify_c13_execution_safety.py`

## Interfaces

`C13PreTradeEnvelope(broker, book, ledger)` rejects unrelated identities and
binds one opaque capability. `submit(intent, now_ns, clock_quality)` derives
all risk and reconciliation evidence internally. Direct `PaperBroker.submit`
is a fail-closed error. `DurableLedger.execution_transaction(expected_head)`
checks the expected head inside the write transaction and restores the book
and sidecar on rollback.

## TDD Sequence

1. Prove expected-head rejection, successful fill/checkpoint persistence and
   complete rollback restoration.
2. Prove source-hash binding, complete market-view evidence and direct-submit
   closure.
3. Prove envelope paper/shadow behavior, capability closure, idempotency,
   race, sidecar, liquidity and failure-injection behavior.
4. Migrate paper fixtures, replay and foundation callers and preserve their
   deterministic results.
5. Run the standalone C13-1 validator and all repository proof gates.

## Verification Commands

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

## Failure Injection

- Change the expected ledger head between preparation and transaction start;
  no fill or idempotency cache entry is accepted.
- Change a portfolio, ledger or market fingerprint; preparation fails closed.
- Remove or alter the sidecar; reconciliation returns a no-trade report and
  never repairs it.
- Raise after the book fill but before checkpoint commit; SQLite, book,
  checkpoint, sidecar, market and report caches return to their prior state.
- Forge the private capability or call the broker directly; both are vetoed.

## Exit Gate

The slice is verified only when focused tests, full tests, the C13-1 validator,
C13-0 validator, repository validation, Proof Engine, Proof Binding, derived
check, compile check and diff check pass. `phase_complete` and
`promotion_allowed` remain `false`; live trading remains `HARD_LOCKED` and
profitability remains `UNPROVEN`.

## Rollback

Revert only the C13-1 feature commits if its exit gate fails. Preserve C13-0
receipt/history and do not rewrite canonical requirements or authority locks.
