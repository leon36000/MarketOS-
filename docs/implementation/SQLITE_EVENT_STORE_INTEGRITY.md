# SQLite Event Store integrity hardening

## Scope

This slice hardens the local conformance `SQLiteEventStore`. It does not select a production database or add a broker, capital path or live execution route.

```yaml
live_trading: HARD_LOCKED
profitability: UNPROVEN
production_backend_selected: false
```

## Guarantees implemented

### Physical append-only enforcement

SQLite owns the first mutation veto. Four authenticated triggers reject direct update and deletion of event and evidence rows:

- `events_no_update`
- `events_no_delete`
- `evidence_no_update`
- `evidence_no_delete`

A compatible database created by an older version receives these guards when reopened. The store authenticates the complete normalized `CREATE TABLE` contracts, including primary-key and uniqueness constraints, before accepting the database. It also requires the exact persistent trigger set, rejects every additional persistent or temporary trigger on the protected ledgers, and verifies each guard's table, operation, unconditional execution and error message. A trigger with the correct name but weakened semantics does not pass.

### Canonical row reconstruction

Event verification reconstructs the complete `EventEnvelope` and enforces:

- contiguous sequence numbers;
- canonical JSON bytes;
- event-domain invariants;
- event ID binding between indexed and serialized representations;
- item digest equality;
- previous-link equality;
- deterministic chain digest equality.

Evidence verification performs the same canonical, item-hash, previous-link and chain checks and requires a non-empty evidence kind.

Malformed JSON is represented by deterministic `ChainVerification.errors`. The diagnostic verifier does not leak parser exceptions.

### Fail-closed constructor and reads

The constructor validates both complete chains and all four guards under `BEGIN IMMEDIATE`. An invalid existing database closes its connection before raising.

`read_all()`, `read_evidence()` and `count()` validate both ledgers in one transactionally stable snapshot. A corrupted evidence ledger therefore blocks an event read or count, and corrupted events block evidence reads. This is an intentional store-wide authority boundary.

### Fail-closed writes without quadratic replay

The store caches the verified count/head of both chains. Before a write it compares:

- `PRAGMA data_version` for commits made by other connections;
- `Connection.total_changes` for writes attempted through the current connection;
- each table's indexed sequence/head tail;
- the four schema guard contracts.

When a witness changed, both complete chains are revalidated under `BEGIN IMMEDIATE`. When no witness changed, a normal append does not replay the full history. The inserted record advances the verified state only after commit.

Two valid store instances can therefore append sequentially to the same WAL database: the stale instance detects the other commit, validates the new history and continues from its current head.

## Error surfaces

- `EVENT_CHAIN_INTEGRITY_FAILURE:<ordered findings>`
- `EVIDENCE_CHAIN_INTEGRITY_FAILURE:<ordered findings>`
- `EVENT_STORE_SCHEMA_INTEGRITY_FAILURE:<trigger>`
- `EVENT_STORE_TAIL_INTEGRITY_FAILURE`
- `SQLITE_EVENT_STORE_CLOSED`

Direct SQL mutations retain the SQLite messages `APPEND_ONLY_EVENTS` and `APPEND_ONLY_EVIDENCE`.

## Non-goals and remaining boundary

The local database is physically append-only through its normal schema and tamper-evident through canonical chains. It is not externally anchored. An attacker with offline file-system authority who rewrites every record, every chain digest and the schema can still create a self-consistent replacement database. External anchoring, replicated consensus and production storage qualification remain separate MarketOS work.

No result of this slice changes phase completion, promotes a strategy, proves profitability or weakens live-trading locks.

## Verification contract

Permanent tests cover:

- direct update/delete vetoes;
- migration of a compatible legacy schema;
- corrupted event/evidence reads, count, append and reopen;
- malformed JSON diagnostics;
- atomic batch and duplicate behavior;
- concurrent valid writers;
- no full-chain revalidation during 200 ordinary appends after initialization.

The exact RED/GREEN workflow receipts and independent review state are recorded on PR33 and issue #32.
