# SQLite Event Store Integrity Design

## Status and authority

This design implements GitHub issue #32 as a bounded foundation hardening slice. It does not select a production database, authorize capital, prove a strategy edge or change any trading route.

```yaml
live_trading: HARD_LOCKED
profitability: UNPROVEN
production_backend_selected: false
```

## Problem

`SQLiteEventStore` persisted event and evidence hash chains, but four authority gaps remained:

1. SQLite allowed direct `UPDATE` and `DELETE` against both ledgers.
2. Public reads deserialized rows without making integrity validation mandatory.
3. opening an existing corrupted database did not fail closed;
4. a naïve fix that replayed the complete history before every append would turn a sequence of appends into quadratic work.

The store must therefore enforce immutability in SQLite, verify canonical records before any public read or externally affected write, and retain an efficient append path when the database has not changed outside the current connection.

## Physical append-only boundary

The schema installs four permanent triggers:

- `events_no_update` and `events_no_delete`, both raising `APPEND_ONLY_EVENTS`;
- `evidence_no_update` and `evidence_no_delete`, both raising `APPEND_ONLY_EVIDENCE`.

Schema initialization uses `CREATE TRIGGER IF NOT EXISTS`, so an existing compatible database receives missing guards. Initialization authenticates the normalized `CREATE TABLE` definitions, including primary-key and uniqueness constraints, requires exactly the four persistent guards, rejects every additional persistent or temporary trigger on the protected ledgers, and rejects a missing, conditional or semantically different contract as `EVENT_STORE_SCHEMA_INTEGRITY_FAILURE`.

## Event-chain verification

Every event row is checked for:

- contiguous sequence identity;
- text and lowercase SHA-256 field shape;
- decodable canonical JSON bytes;
- successful reconstruction of `EventEnvelope` and its domain invariants;
- equality between the indexed `event_id` and reconstructed event identity;
- equality between the stored event digest and the reconstructed digest;
- exact previous-link equality;
- exact deterministic chain digest.

The canonical Decimal marker is reserved: an exact user mapping of
`{"$decimal": ...}` is rejected before persistence so the decoder remains
injective over accepted payloads. Genuine `Decimal` values remain supported.

Malformed JSON is represented in `ChainVerification.errors`; it must never escape as a raw `JSONDecodeError` from a verifier.

## Evidence-chain verification

Every evidence row is checked for:

- contiguous sequence identity;
- non-empty evidence kind;
- text and lowercase SHA-256 field shape;
- decodable canonical JSON bytes;
- equality between stored and reconstructed evidence digests;
- exact previous-link equality;
- exact deterministic chain digest.

The store persistence boundary is narrower than the general fingerprinting
helper. Accepted payloads are JSON scalars, `Decimal`, mappings with unique
string keys, and reconstructible sequences. Event payload tuples are the
internal representation produced by `EventEnvelope` for JSON lists; evidence
payloads use JSON lists. Enums, datetime/UUID/Path values, dataclasses,
custom `canonical_dict()` objects, sets, non-string keys, key collisions, and
reserved canonical tags are rejected before persistence. Rich replay reports
are explicitly reduced to this canonical wire payload before evidence append.

## Fail-closed surfaces

Initialization uses `BEGIN IMMEDIATE` and validates both complete ledgers plus all four schema guards before the constructor returns. An invalid database closes its connection and raises `InvariantViolation`.

`read_all()`, `read_evidence()` and `count()` materialize one transactionally stable snapshot, validate both chains and the schema guards, and return nothing if either ledger is invalid. This global boundary prevents an intact event chain from masking a corrupted evidence chain or the reverse.

`verify_chain()` and `verify_evidence_chain()` remain diagnostic methods: they return structured failure reports for malformed rows rather than asserting validity.

## Efficient write boundary

A verified in-memory state stores the count and head digest of each ledger together with:

- `PRAGMA data_version`, which changes after commits from another connection;
- `sqlite3.Connection.total_changes`, which detects writes made through the current connection;
- the current indexed tail of each ledger.

Before a normal append, `BEGIN IMMEDIATE` creates a stable writer boundary. When versions and tails match the verified cache, the store validates only the fixed-size schema guard set and proceeds without a full replay. When another connection or local mutation changed the database, both complete chains are revalidated before any insert or idempotent return.

A successful append advances the cached count/head directly from the inserted record. A failed transaction does not promote uncommitted state. At most one subsequent full verification may occur after a rolled-back local write because SQLite's `total_changes` includes rolled-back attempts.

## Concurrency semantics

Two valid `SQLiteEventStore` instances may append sequentially to the same WAL database. The stale instance detects the other connection's commit through `data_version`, revalidates both ledgers under `BEGIN IMMEDIATE`, refreshes its verified state and appends to the current head.

The design does not claim distributed consensus, Byzantine resistance or protection against an attacker who rewrites the complete database and every digest while the store is offline. External anchoring remains a separate architecture requirement.

## Permanent tests

The implementation is rejected unless tests prove:

- all four direct mutation vetoes;
- guard installation on a legacy compatible schema;
- event and evidence corruption block reads, count, append and reopen;
- malformed event and evidence JSON produce structured verification errors;
- reserved Decimal-marker maps are rejected before persistence while real Decimal values round-trip;
- non-reconstructible payload types, reserved tags, and canonical key collisions are rejected;
- replay execution-report evidence is reduced to a reconstructible canonical wire payload;
- valid concurrent writers refresh stale verified state;
- 100 event appends followed by 100 evidence appends perform no full-chain verification after initialization;
- prior durability, idempotency and atomic batch behavior remains green.
