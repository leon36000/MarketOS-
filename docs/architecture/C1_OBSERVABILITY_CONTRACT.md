# C1 Observability Contract

## Required correlation chain

```text
source_data -> dataset -> feature -> model -> decision -> risk
-> order -> fill -> reconciliation -> outcome
```

Every record must carry stable trace/correlation IDs, event time, knowledge time, component version and evidence pointers where applicable.

## Signals

- metrics for availability, freshness, latency, backlog, error rate, cost and resource pressure;
- structured logs with bounded cardinality and secret redaction;
- traces across agent, numerical, risk and execution boundaries;
- audit records for configuration, permission and lifecycle changes.

## Alert requirements

Every alert policy declares:

- severity;
- deterministic deduplication key;
- owner and receiver;
- acknowledgement deadline;
- escalation path;
- silence duration and authority;
- runbook URL/path;
- recovery condition;
- evidence retention.

No alert is considered implemented solely because a metric exists.
