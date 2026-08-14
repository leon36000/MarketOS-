# Venue Calendar and Point-in-Time Feature Store — Implementation Slice

## Implemented

This slice extends canonical market data with provider-neutral session and feature contracts:

- append-only venue-session revisions with stable UUID identity;
- latest-known early closes, cancellations, halts and schedule corrections;
- half-open UTC session intervals and deterministic next-open queries;
- explicit ambiguity when multiple latest-known sessions overlap;
- immutable feature definitions with code, configuration, input-schema and rights hashes;
- explicit `non_display`, `historical_replay` and `derived_data` admission;
- exact close-to-close return materialization with declared quantization;
- input-bar, definition and rights lineage in every point;
- availability equal to the latest bar or session revision used;
- calendar-aware filtering that obeys the historical knowledge cutoff;
- append-only SQLite feature revisions with latest-known queries;
- stored feature hash verification and idempotent duplicate handling;
- independent eight-check acceptance verification and dedicated CI.

## Deliberate non-selection

No exchange-calendar vendor, timezone library, feature platform, distributed compute engine, online feature cache or production database is selected. The in-memory UTC session book and SQLite feature store are local conformance backends only.

## Financial boundary

A deterministic feature is not a strategy and does not establish predictive value. This slice proves temporal, rights, lineage and storage contracts only.

```yaml
calendar_provider_selected: false
feature_backend_selected: false
feature_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

Calendar corrections and late market observations can produce later point-in-time views, but they never rewrite what was available at an earlier cutoff.
