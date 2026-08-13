# C2 — Data Quality Contract

## Dimensions

- provenance and legal identity;
- temporal correctness;
- completeness and coverage;
- uniqueness and sequence;
- schema and semantic validity;
- cross-field and cross-source consistency;
- correction/retraction history;
- survivorship and universe integrity;
- latency and freshness;
- reproducibility;
- rights compliance.

## QualityEnvelope

```yaml
dataset_version:
source_id:
raw_payload_hashes:
schema_hash:
record_count:
coverage:
gap_count:
duplicate_count:
out_of_order_count:
unknown_identifier_count:
correction_count:
quarantine_count:
rights_policy_id:
checks:
status: pass|degraded|quarantined|blocked
```

## Hard failures

- payload hash or schema mismatch;
- event available before persistence/knowledge time;
- invalid source sequence without recovery;
- unresolvable identifier collision;
- deleted inactive/delisted securities;
- corporate-action correction applied retrospectively before knowledge time;
- unknown licence right for the requested operation;
- incompatible units or currencies;
- silent timezone or daylight-saving reinterpretation;
- source history replaced without retained version.

## Statistical monitoring

Use field-level null rates, quantile/range checks, robust outlier detection, distribution drift, timestamp/latency distributions and cross-source residuals. Statistical anomalies create evidence for review; they do not automatically rewrite data.

## Missing data

Missing is represented explicitly with reason and detection time. Forward-fill, interpolation, imputation or synthetic completion is a derived transformation with method, horizon, confidence and non-promotable restrictions where appropriate.

## Reprocessing

Every transformation is content-addressed by raw inputs, code, configuration and dependency versions. Reprocessing creates a new version; it never overwrites an experiment's input identity.

## Service levels

SLAs and SLOs are role-specific: research can tolerate delay that execution cannot. Data freshness failure automatically disables dependent strategies before it becomes a pricing assumption.
