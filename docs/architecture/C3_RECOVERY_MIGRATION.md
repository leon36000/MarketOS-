# C3 Migration, Retention and Recovery

## Migration

Use expand–migrate–contract. New schemas are added first, data is copied or dual-written when necessary, old and new point-in-time fingerprints are compared, readers switch only after equivalence, and destructive cleanup occurs after a rollback window.

Every migration records source/target schema, code and dependency hashes, data versions, row/content fingerprints, rights checks, reviewer, rollback and completion receipt.

## Retention

Experiment references, evidence, negative results and incident records protect their required data versions. Garbage collection starts with a dry-run reachability report. Snapshot or time-travel claims are valid only while all referenced metadata and files remain retained.

Legal or contractual deletion can override normal retention. The deletion receipt records scope, authority, affected experiments and any remaining permitted non-reconstructive evidence.

## Recovery

A backup is unverified until restored into an isolated clean environment. Recovery verifies catalogs, object references, temporal views, dataset identities, lineage and semantic query fingerprints.

RPO and RTO are defined by data class, not globally. Raw licensed data may use a reacquisition plan only when contract, source availability and exact-version reproducibility make it credible.

## Failure tests

Partial metadata/data commit, lost catalog, corrupted object, stale snapshot, catalog rollback, writer crash, concurrent migration, schema mismatch, missing encryption key, retention mistake and complete clean-host rebuild.
