# C1 — Observability Contract

## Correlation chain

```text
source_data -> dataset -> feature -> model -> decision -> risk
-> order -> fill -> reconciliation -> outcome
```

Every record carries a stable correlation ID, event time, knowledge time, component version, configuration hash and evidence pointer where applicable.

## Telemetry boundary

OpenTelemetry and OTLP are the vendor-neutral contract. Grafana Alloy stable/default engine is the preferred edge-collector candidate. The experimental Alloy OTel Engine is excluded from the baseline. OpenTelemetry Collector Contrib remains an alternative or gateway.

## Signals

- metrics for availability, freshness, latency, backlog, errors, cost and resource pressure;
- structured logs with redaction and bounded fields;
- traces across model, numerical, risk and execution boundaries;
- audit records for configuration, permission and lifecycle changes.

## Sampling and cardinality

Risk, execution, security and configuration-change traces use full sampling. Research and simulation may use bounded sampling with the decision recorded. High-cardinality identifiers do not become unbounded metric labels; each signal has a monitored cardinality budget.

## Required metrics

Source freshness, sequence gaps, capture latency, data quarantine, queue lag, replay fingerprint mismatch, model latency/cost/fallback, numerical divergence, risk vetoes, order and reconciliation state, resource pressure, backup age, restore result, alert delivery and acknowledgement latency.

## Backend candidates

Prometheus, Loki, Tempo and Grafana form the preferred initial comparison set. Loki retention must be explicit. Durable Tempo deployments require object storage. Compact alternatives remain open until benchmarks quantify resource and operational cost.

## Meta-monitoring

The telemetry pipeline monitors receiver rejects, dropped data, queue saturation, export failure, clock uncertainty and backend availability. Missing telemetry from a critical service is itself a fault.

## Data safety

Collectors bind only to approved interfaces, authenticate remote exports, bound memory use and redact confidential values. Telemetry cannot contain provider credentials, broker credentials or raw authentication tokens.
