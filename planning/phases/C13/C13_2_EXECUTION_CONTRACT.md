# C13-2 — Authenticated Checkpoint Reconstruction Contract

## Objective

Provide a narrowly bounded restart path for a paper/shadow authoritative book
when, and only when, the latest checkpoint is authenticated by the current
journal head and the v2 checkpoint witness sidecar.

This slice is verified but does not complete C13. It keeps `HARD_LOCKED`,
`UNPROVEN`, and `promotion_allowed = false` unchanged.

## Contract

- A genuinely new path with no database rows may create the v2 genesis anchor.
- An existing database without its sidecar fails with
  `JOURNAL_INTEGRITY_FAILURE`.
- A legacy v1 sidecar is readable for audit/reconciliation, but non-empty
  authoritative restoration and mutation fail with
  `BOOK_CHECKPOINT_WITNESS_REQUIRED`; there is no automatic upgrade.
- The v2 sidecar authenticates journal head fields and the latest checkpoint
  sequence and transitive record digest; each v2 record commits its
  predecessor digest.
- A checkpoint rewrite that recomputes its SQLite row digest but disagrees
  with the sidecar fails with `BOOK_CHECKPOINT_WITNESS_FAILURE`.
- Only the checkpoint matching the current ledger SHA may restore a book, and
  restoration holds a SQLite writer lock through final publication and a
  second head check.
- Cash is derived from the journal prefix named by the checkpoint; positions
  and realized P&L come from the authenticated snapshot only.
- Snapshot invariants reject malformed currencies, digests, ordering,
  quantities, costs, currencies, cash, and capture times.
- Sidecar replacement is atomic and is restored on transaction failure.

## Out of scope

This does not provide position inference from journal postings, broker/OMS/EMS
integration, live order submission, kill-switch routing, production accounting,
security qualification, chaos/DR evidence, or completion of C13-C16.

## Exit gate

The focused tests, independent validator, repository validator, full unittest
suite, Proof Engine, Proof Binding, compile check, derived-file check and
`git diff --check` must pass. The evidence must preserve
`phase_complete = false`, `promotion_allowed = false`,
`live_trading_state = HARD_LOCKED`, and `profitability_state = UNPROVEN`.
