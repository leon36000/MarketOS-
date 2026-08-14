# Security Master and Local Data Fabric — Implementation Slice

## Implemented

This slice extends the deterministic paper core with a standard-library local conformance backend:

- UUID-first instruments, venues and listings;
- bitemporal symbol and external-identifier assignment;
- symbol reuse and delisted-history preservation;
- append-only corporate-action revisions, corrections, cancellations and quarantine;
- adjustment factors as a derived view, never raw-price mutation;
- complete fail-closed data-rights policies;
- content-addressed immutable raw bytes with append-only retrieval receipts;
- SQLite bitemporal facts with latest-known revision semantics, hash verification and conflict quarantine;
- staged, rights/quality/lineage-gated atomic dataset publication with committed-byte re-verification;
- deterministic content roots, immutable versions and idempotent retries;
- backup manifests and semantic corruption detection.

## Deliberate non-selection

No commercial provider, object store, lake format, temporal database, hot-store or lineage backend is selected. The local filesystem and SQLite implementations prove interfaces and invariants only. DuckLake/Iceberg, Postgres/XTDB, QuestDB/ClickHouse and cloud backends remain separate target bake-offs.

## Authority boundary

```yaml
provider_selected: false
production_storage_engine_selected: false
strategy_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

Raw and canonical data remain distinct. Unknown rights deny. Conflicts are surfaced rather than silently averaged. A backup is not considered verified merely because it was written; restore bytes and semantic checks remain mandatory.
