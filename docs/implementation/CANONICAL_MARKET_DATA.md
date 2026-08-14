# Canonical Market Data and Quality — Implementation Slice

## Implemented

This slice extends the local Security Master/Data Fabric with provider-neutral canonical market-data contracts:

- immutable quote and trade observations tied to listing and venue UUIDs;
- source, channel and source-sequence preservation;
- economic, receipt, monotonic and strategy-availability times;
- raw content-addressed evidence linkage for every observation;
- append-only corrections and cancellations with point-in-time knowledge cutoffs;
- deterministic idempotency and conflicting-version rejection;
- sequence-gap, sequence-regression and sequence-collision quarantine;
- crossed/empty quote, zero trade, future-skew and excessive-latency quality gates;
- stored observation, raw-source and quality-decision hash verification on read;
- exact quality-policy and rights-policy hashes preserved in every admission decision;
- accepted and quarantined streams kept distinct;
- exact deterministic OHLCV bars with complete-bucket, no-look-ahead and explicit derived-data rights;
- late arrivals affect only later point-in-time bar rebuilds;
- independent eight-check acceptance verification and dedicated CI.

## Evidence classification

The SQLite store and local raw-evidence directory are conformance backends. They establish contracts, deterministic behavior and failure handling. They do not establish vendor semantics, exchange completeness, packet-loss recovery, target latency, production throughput or licensed usage.

## Deliberate non-selection

No market-data vendor, exchange feed, SIP, direct-feed protocol, capture appliance, hot time-series engine, Kafka/NATS topology or cloud region is selected. Those remain target bake-offs against the same canonical contracts.

## Authority boundary

```yaml
provider_selected: false
production_feed_qualified: false
strategy_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

Quarantined data cannot enter accepted streams or bars. A correction never overwrites the original. A bar is unavailable before both the interval close and all included observations were available to the strategy.
