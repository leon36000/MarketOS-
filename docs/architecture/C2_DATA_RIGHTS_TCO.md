# C2 — Data Rights and Total-Cost Contract

## Rights are executable policy

A purchase receipt or API key does not prove a right. MARKET-OS stores a versioned `RightsPolicy` for each product, use, user class, environment and date. Unknown rights deny the action.

## RightsPolicy fields

```yaml
policy_id:
provider:
product:
contract_version:
effective_from:
effective_to:
professional_status:
display:
non_display:
users:
devices:
servers:
sites:
applications:
storage:
retention_period:
historical_replay:
derived_data:
cloud_processing:
cloud_regions:
redistribution:
model_training:
embeddings:
model_output_use:
audit_reporting:
termination_deletion:
exit_export:
source_documents:
reviewed_by:
status: verified|partial|unknown|expired|disputed
```

Rights are not inferred across products. Display, non-display, derived data, training and embedding are separate permissions.

## Enforcement points

Rights checks occur before:

- ingestion and durable storage;
- copy to cloud or remote node;
- feature/derived dataset construction;
- embedding or model training;
- export, dashboard display or redistribution;
- backup retention;
- experiment reproduction after contract end;
- provider termination and deletion.

A denied action produces an auditable veto. Agents cannot modify rights policy.

## TCOScenario

```yaml
scenario_id:
provider_products:
asset_classes:
venues:
depth:
history:
live_users:
servers:
regions:
subscription:
exchange_pass_through:
minimum_commitment:
usage_or_record_fee:
connectivity:
storage:
egress:
compute:
normalization:
quality_monitoring:
support:
compliance_reporting:
migration_and_exit:
contingency_reserve:
uncertainty_range:
assumptions:
quote_date:
valid_until:
```

No missing cost is treated as zero. Unknown costs keep the scenario incomplete.

## Scenario families

- public/official data baseline;
- low-cost historical research;
- US/Canada L1 shadow/paper;
- selective L2 execution research;
- selective L3 queue-position research;
- options and volatility;
- news/social event intelligence;
- full institutional/reference package;
- cloud-burst versus local retention.

## Decision metric

```text
conservative incremental value
- direct fees
- exchange fees
- storage/egress/compute
- integration and monitoring cost
- compliance and exit cost
- uncertainty reserve
```

A dataset is admitted only for a role. A cheaper product cannot silently substitute for missing semantics, and a premium product must prove marginal value.

## Termination

Before activation, define export, reproducibility, deletion, model/embedding disposition, audit evidence and replacement. If historical bytes must be deleted, preserve only permitted hashes, schemas, code and non-reconstructive evidence.
