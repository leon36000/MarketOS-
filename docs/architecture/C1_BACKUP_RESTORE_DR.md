# C1 — Backup, Restore and Disaster-Recovery Contract

## Truth rule

A successful backup command is not a verified backup. Verification requires integrity checks plus restore into an isolated clean environment and comparison to expected hashes and invariants.

## Data classes

| Class | Examples | Policy |
|---|---|---|
| A | canon, requirements, decisions and evidence ledgers | encrypted, versioned, offline copy, frequent verification |
| B | configuration, dashboards and operational metadata | encrypted backup and automated restore drill |
| C | licensed bulk data | rights-aware retention, replica or reacquisition plan |
| D | rebuildable caches | excluded by default; rebuild manifest retained |

## Candidate

restic is the preferred encrypted-backup candidate. The writer identity is append-only where possible and cannot prune. A separate administrative identity performs retention and prune operations after review.

## Required workflow

```text
snapshot inventory
-> application-consistent checkpoint
-> backup with immutable input manifest
-> repository integrity check
-> restore to a clean target
-> validate schemas, hashes and semantic invariants
-> produce restore receipt
```

## Objectives

C1 defines data classes and measurement. C3 finalizes data-fabric objectives; C13 finalizes portfolio, risk and execution-state objectives. Any unmeasured RPO or RTO remains `UNSET`.

## Restore receipt

A receipt records repository ID, snapshot ID, source manifest, restore environment, timestamps, commands, restored hashes, semantic checks, missing objects, operator identity and result.

## Failure tests

- corrupt repository;
- lost writer or administrative identity;
- disk full;
- unsupported schema version;
- missing encryption key;
- clean-host restore without network;
- stale snapshot;
- backup containing a forbidden confidential value.

## Deletion boundary

Retention never overrides data-licence deletion rules or the negative-result retention policy. Deletion requires an auditable policy decision.
