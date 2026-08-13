# C3 Execution Contract

## Objective

Design replaceable storage roles for immutable evidence, canonical columnar history, bitemporal truth, recent low-latency views, reproducible query, dataset publication, lineage and recovery.

## Exclusions

No engine selection, infrastructure deployment, data deletion, live activation or claim of target performance.

## Required future interfaces

`RawEvidenceVault`, `CanonicalLake`, `TemporalTruth`, `RecentViewStore`, `PointInTimeQuery`, `DatasetPublisher`, `LineageSink`, `MigrationPlan`, `RetentionPolicy` and `RecoveryReceipt`.

## Test-first sequence

1. Reject raw overwrite and partial publication.
2. Reject queries that omit economic or knowledge cutoff.
3. Require logical fingerprints to survive compaction and path changes.
4. Inject metadata/data split commits and require recovery or quarantine.
5. Migrate schema through expand–migrate–contract and compare old/new fingerprints.
6. Protect experiment-referenced versions from retention cleanup.
7. Corrupt an object/catalog and require clean-environment restore plus semantic checks.
8. Prove every recent/materialized view can be rebuilt from authoritative history.

## Candidate bake-offs

- DuckLake versus Apache Iceberg for the canonical lake.
- PostgreSQL bitemporal baseline versus XTDB for temporal truth.
- QuestDB versus ClickHouse for recent operational views.
- DuckDB/Polars/Arrow for local query and dataset construction.
- Optional Materialize/RisingWave only if maintained views justify another stateful service.

## Verification

```bash
python -m unittest discover -s tests -v
python tools/validate_c3_design.py --root . --json
python tools/validate_repository.py --root . --json
python tools/regenerate_derived.py --root . --check --json
```

## Exit gate

`C3_DESIGN_GATE_PASS` requires nine role contracts, three mapped requirements, migration/retention/recovery rules, candidate matrices, adverse mutations and explicit engine/target gates left open.

## Rollback

Remove the signed C3 delta, restore the C2 checkpoint, regenerate derived files and reproduce C1/C2 validation.
