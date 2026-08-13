# C1 Source Ledger

Primary documentation to refresh and pin during implementation:

| Candidate | Purpose | Source |
|---|---|---|
| Podman Quadlet | rootless standalone lifecycle | https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html |
| K3s | optional lightweight Kubernetes | https://docs.k3s.io/installation/requirements |
| OpenTelemetry Collector | telemetry contract | https://opentelemetry.io/docs/collector/ |
| Grafana Alloy | OTel-compatible collector/distribution | https://grafana.com/docs/alloy/latest/ |
| Alertmanager | grouping, routing and deduplication | https://prometheus.io/docs/alerting/latest/alertmanager/ |
| OpenBao KV v2 | versioned secret storage candidate | https://openbao.org/docs/secrets/kv/kv-v2/ |
| OpenBao AppRole | machine identity candidate | https://openbao.org/docs/auth/approle/ |
| OpenBao Transit | encryption service candidate | https://openbao.org/docs/secrets/transit/ |
| restic | backup integrity and restore drills | https://restic.readthedocs.io/ |

All exact versions, licenses, images and release provenance remain unresolved until the C1 bake-off.
