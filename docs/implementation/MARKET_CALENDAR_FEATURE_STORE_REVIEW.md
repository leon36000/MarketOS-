# Venue Calendar and Point-in-Time Feature Store — Independent Review

## Scope reviewed

- append-only venue-session revisions and latest-known schedule semantics;
- ISO session dates, early closes, cancellations, halts and overlap ambiguity;
- rights-gated point-in-time feature materialization;
- bar and calendar-session lineage;
- canonical input roots and availability times;
- append-only feature revisions, exact-version queries and stored integrity.

## Findings corrected before review closure

1. Calendar dates are validated as real ISO dates, not merely strings matching `YYYY-MM-DD`.
2. Every feature point records the exact session-revision hashes used alongside the bar hashes.
3. The canonical input root must equal the hash of both bar and calendar-session lineage.
4. Feature reads require the exact feature version; no implicit newest-version selection is permitted.
5. Independent point identities occupying one semantic feature key fail as `AMBIGUOUS_FEATURE_POINT`.
6. Duplicate appends verify the stored row before returning an idempotent result, preventing corruption from being masked.
7. Calendar revisions change later point-in-time feature lineage without rewriting earlier historical views.

## Verification model

The permanent workflow executes contract, acceptance and adversarial tests, then the complete repository suite and all prior acceptance verifiers. The local calendar and SQLite Feature Store remain conformance implementations; they do not select a production provider or backend.

```yaml
calendar_provider_selected: false
feature_backend_selected: false
feature_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

## Verdict

`NO_BLOCKING_LOCAL_CONFORMANCE_FINDING — CALENDAR_PROVIDER_AND_PRODUCTION_FEATURE_BACKEND_QUALIFICATION_REMAIN_OPEN`.
