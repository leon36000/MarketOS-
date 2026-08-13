# C1 — Alerting and Notification Contract

## Routing authority

Prometheus Alertmanager is the preferred routing candidate because it provides grouping, routing, inhibition, silences and deduplication. Delivery is treated as at-least-once; receivers must be idempotent and tolerate duplicates.

## Severity

| Level | Meaning | Response |
|---|---|---|
| S0_CRITICAL | integrity or financial-safety threat | immediate page, acknowledgement and approved safe halt |
| S1_HIGH | material service, data or capacity degradation | immediate notification and acknowledgement |
| S2_WARNING | degraded redundancy, approaching limits or drift | batched notification and tracked remediation |
| S3_INFO | expected lifecycle event | dashboard or digest only |

## Mandatory fields

Every policy defines stable rule ID, version, severity, owner, deduplication key, firing and recovery conditions, hysteresis, receiver, fallback, acknowledgement deadline, escalation, silence authority, runbook and evidence retention.

## Channels

- ntfy is the preferred personal/mobile candidate;
- email and authenticated webhooks are secondary;
- Gotify is an alternative;
- Apprise remains a watchlist fan-out layer.

A notification channel cannot authorize a transaction, modify limits or reveal a confidential value. Mobile actions are restricted to acknowledgement, evidence viewing and approved safe-stop commands.

## Noise control

Group by root incident and failure domain, inhibit derivative alerts, enforce storm limits, measure latency and duplicates, and test receiver failure and network partition.

## Mandatory families

Stale data, clock uncertainty, sequence gap, failed numerical or risk service, reconciliation divergence, unauthorized configuration change, credential exposure, storage exhaustion, backup age, failed restore drill, hardware fault and alert-pipeline failure.
