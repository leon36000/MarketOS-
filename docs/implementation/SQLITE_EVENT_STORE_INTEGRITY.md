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

A compatible database created by an older version receives missing guards when reopened. Before creating anything in an existing ledger database, the store authenticates the complete normalized `CREATE TABLE` contracts, existing trigger contracts and both ledgers. An incompatible schema, weakened trigger or corrupt row is rejected without silently repairing the database. Once that preflight passes, missing guards may be installed; the final state requires the exact persistent trigger set, rejects every additional persistent or temporary trigger on the protected ledgers, and verifies each guard's table, operation, unconditional execution and error message.

### Canonical row reconstruction

Event verification reconstructs the complete `EventEnvelope` and enforces:

- contiguous sequence numbers;
- canonical JSON bytes;
- event-domain invariants;
- event ID binding between indexed and serialized representations;
- item digest equality;
- previous-link equality;
- deterministic chain digest equality.

The exact `{"$decimal": ...}` mapping is reserved for the canonical Decimal
encoding. Store writes reject that ambiguous user mapping before persistence,
while genuine `Decimal` values continue to round-trip as Decimal values.

The persistence boundary is deliberately narrower than the general
fingerprinting helper: payloads may contain JSON scalars, `Decimal`, mappings
with unique string keys, and reconstructible sequences. Event payload tuples
are the internal representation produced by `EventEnvelope` for JSON lists;
evidence payloads use JSON lists. Enums, datetime/UUID/Path values,
dataclasses, custom `canonical_dict()` objects, sets, non-string keys, key
collisions, and reserved canonical tags are rejected before persistence.
The same boundary is applied while reconstructing historical rows, so a
reserved tag already present on disk fails closed instead of becoming a
readable but non-reinsertable record.
Replay canonicalizes its rich execution report into this wire payload before
writing evidence.

Evidence verification performs the same canonical, item-hash, previous-link and chain checks and requires a non-empty evidence kind.

Malformed JSON is represented by deterministic `ChainVerification.errors`. The diagnostic verifier does not leak parser exceptions.

### Fail-closed constructor and reads

The constructor validates both complete chains and all four guards under `BEGIN IMMEDIATE`. Existing ledger databases perform their table/row preflight and installation of missing guards inside one writer transaction, so no writer can change the database between validation and schema completion. Only a compatible schema with valid rows may receive missing guards. An invalid existing database closes its connection before raising without silent repair.

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
- `AMBIGUOUS_DECIMAL_MARKER`
- `AMBIGUOUS_CANONICAL_TAG:<tag>`
- `NON_CANONICAL_PAYLOAD_KEYS`
- `NON_RECONSTRUCTIBLE_PAYLOAD_TYPE:<type>`
- `SQLITE_EVENT_STORE_CLOSED`

Direct SQL mutations retain the SQLite messages `APPEND_ONLY_EVENTS` and `APPEND_ONLY_EVIDENCE`.

## Non-goals and remaining boundary

The local database is physically append-only through its normal schema and tamper-evident through canonical chains. It is not externally anchored. An attacker with offline file-system authority who rewrites every record, every chain digest and the schema can still create a self-consistent replacement database. External anchoring, replicated consensus and production storage qualification remain separate MarketOS work.

No result of this slice changes phase completion, promotes a strategy, proves profitability or weakens live-trading locks.

## Verification contract

Permanent tests cover:

- direct update/delete vetoes;
- migration of a compatible legacy schema;
- rejection of historical non-reconstructible payloads;
- rejection of an incompatible existing schema without adding ledger objects;
- rejection of an incompatible existing schema without changing its journal mode;
- writer exclusion throughout existing-schema preflight and guard installation;
- corrupted event/evidence reads, count, append and reopen;
- malformed JSON diagnostics;
- atomic batch and duplicate behavior;
- valid multi-connection writers refresh stale verified state;
- no full-chain revalidation during 200 ordinary appends after initialization.

The exact RED/GREEN workflow receipts and independent review state are recorded on PR33 and issue #32.
