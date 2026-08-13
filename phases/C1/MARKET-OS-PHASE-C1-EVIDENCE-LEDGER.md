# C1 Evidence Ledger

## Primary evidence families

- Podman rootless and Quadlet documentation;
- K3s requirements and security documentation;
- OpenTelemetry Collector and security documentation;
- Grafana Alloy documentation and Grafana Agent EOL notice;
- Prometheus Alertmanager and high-availability semantics;
- Loki retention and Tempo storage documentation;
- OpenBao KV, AppRole and Transit documentation;
- systemd credential documentation;
- restic backup and restore documentation;
- notification, private-access and registry candidates.

## Negative findings retained

- Portainer's documented Podman support does not fit the rootless baseline.
- Grafana Agent is EOL and cannot be introduced.
- Alloy's alternative OTel engine is experimental and excluded from the baseline.
- Alertmanager HA can deliver duplicates by design; receivers must be idempotent.
- A backup without a clean restore remains unverified.
- K3s resource minimums do not prove appropriate MARKET-OS sizing.

## Unresolved evidence

Exact versions, images, licences, signatures, resource budgets, compact-stack comparisons, identity-provider choice, object storage, RPO/RTO and target-node tests remain open.
