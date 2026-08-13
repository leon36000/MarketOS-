# C3 Data Fabric Reference Architecture

## Principle

No single database or table format is allowed to become capture system, historical truth, hot store, local query engine, lineage authority and backup system simultaneously. Each role has a separate contract and replacement path.

```text
sources
  -> capture gateway
  -> immutable raw evidence + retrieval ledger
  -> canonical append-only lake
  -> temporal truth and correction views
  -> hot recent window / incremental views
  -> point-in-time dataset builder
  -> replay, research, models and agents

lineage, rights, quality and recovery observe every transition.
```

## R0 raw evidence

Stores exact received bytes, envelope, timestamps, headers, schema fingerprint and content hash. Objects are content-addressed and immutable. A parser bug, source correction or new normalizer never changes an old object.

## R1 retrieval audit

Records attempts, failures, retries, conditional requests, response status, first byte, persistence time and links to prior representations. A 304 references a previously verified representation rather than creating fictional bytes.

## R2 canonical lake

Stores normalized append-only facts and versions in open columnar files. Partitioning and compaction are physical optimizations; logical dataset identity is independent from paths and file grouping.

## R3 temporal truth

Provides valid-time and knowledge/system-time queries for identities, facts, revisions, retractions and source disagreements. The hot store cannot replace this role.

## R4 hot market store

Serves recent data, status and operational views with low latency. It is rebuildable from authoritative history. Retention, one-timestamp limits and update semantics are explicit.

## R5 local query

Supports reproducible SQL/dataframe research directly over pinned datasets. DuckDB and Polars/Arrow remain candidates behind MARKET-OS interfaces.

## R6 incremental views

Optional. Materialize or RisingWave is admitted only if maintained views reduce latency/operations enough to justify another stateful system. Every view is rebuildable and non-authoritative.

## R7 dataset builder

Publishes a dataset only after input identities, cutoffs, schema, code, dependencies, rights, quality and lineage all pass. Publication is atomic.

## R8 lineage and evidence

OpenLineage-compatible job, run and dataset events are the interoperability contract. Run states include start, progress, completion, abort and failure. The backend is replaceable.

## R9 recovery

Backups, table snapshots and branches are not interchangeable. Recovery plans cover raw bytes, metadata catalogs, truth stores, hot stores, lineage and configuration independently, then test system-level reconstruction.

## Authority order

```text
raw bytes and signed source evidence
> canonical event/fact versions
> temporal truth view
> published point-in-time dataset
> hot store and materialized views
> cache
```

A faster derivative can never silently outrank its source.
