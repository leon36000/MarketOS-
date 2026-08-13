# C2 — Source Admission and Reconciliation

## Principle

No provider is universally authoritative. Authority is domain-, venue-, field-, time- and contract-specific. A normalized vendor can be operationally excellent while remaining downstream of primary sources.

## Source tiers

| Tier | Examples | Default use |
|---|---|---|
| T0_PRIMARY | issuer, regulator, exchange notice, depository, central bank, statistics agency | legal/status/fact authority where applicable |
| T1_MARKET_AUTHORITY | SIP, direct exchange feed, licensed reference/corporate-action vendor | market and reference production candidates |
| T2_NORMALIZED | broker, aggregator, normalized vendor | convenience, operations and corroboration |
| T3_DISCOVERY | web, social, unknown third party | discovery only until corroborated |

Tier is not a universal score. A source can be T0 for one field and irrelevant for another.

## SourceQualification

```yaml
source_id:
legal_provider:
product_id:
source_tier:
domains:
venues:
asset_classes:
coverage_start:
coverage_end:
update_frequency:
timestamps:
sequence_semantics:
correction_policy:
retraction_policy:
schema_version:
raw_access:
normalization:
identifiers:
licence_policy_id:
tco_scenario_id:
sample_hashes:
quality_results:
reconciliation_results:
status: queued|screened|evidenced|sampled|benchmarked|admitted|rejected|watchlist|blocked
```

## Admission pipeline

```text
identity and legal owner
-> exact product/schema/version
-> raw sample and hash
-> timestamp and sequence tests
-> correction/retraction replay
-> coverage and survivorship checks
-> rights and TCO completion
-> security/supply-chain checks
-> cross-source reconciliation
-> role-specific decision
```

Unknown or unavailable evidence produces `BLOCKED`, not assumed compliance.

## Reconciliation model

Every comparison defines a canonical key, temporal window, units, tolerance and expected source relationship. Differences are classified:

- exact match;
- rounding/normalization difference;
- timing difference;
- source correction;
- missing observation;
- identifier mismatch;
- semantic/schema mismatch;
- unresolved contradiction.

A `ReconciliationDecision` records all values, source versions, evidence, rule, reviewer and outcome. Material contradictions quarantine the field or dataset; they are never averaged without a documented model.

## Multi-source policy

- T0/T1 sources anchor legal status, venue state and primary announcements.
- A normalized source may be admitted for latency or convenience after periodic primary-source checks.
- Broker data is reconciled against internal order/execution records and independent market/reference sources.
- Web/social inputs cannot directly repair authoritative reference data.

## Drift monitoring

Monitor schema fingerprints, enum changes, field null rates, timestamp distribution, sequence gaps, duplicate rates, symbol/identifier churn, correction frequency and source disagreement. Silent schema drift stops ingestion for affected fields.

## Exit and replacement

Each admitted role has an export format, replacement candidate, dual-run window, contract end date, deletion obligations and historical replay strategy. Vendor exit cannot destroy experiment reproducibility.
