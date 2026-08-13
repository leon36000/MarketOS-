# C3 Temporal Truth Store

The truth role stores facts, versions, corrections, retractions and source disagreements with both economic-validity time and knowledge/system time.

PostgreSQL with explicit bitemporal tables is the portable baseline. XTDB is the native-bitemporal candidate. Neither is selected until identical queries, invalidations, migrations, backup and recovery are reproduced.

A query must state both cutoffs. Missing knowledge time, silent overwrite, retroactive correction or loss of a superseded version is a hard failure.

The truth store is metadata/fact authority, not a tick-scale hot store or object archive. Large raw payloads stay in the evidence vault and are referenced by hash.
