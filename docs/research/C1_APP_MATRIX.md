# C1 Application Matrix

| Component | Role | Status |
|---|---|---|
| Podman Quadlet | standalone lifecycle | preferred candidate |
| K3s | optional cluster | optional candidate |
| OpenTelemetry | telemetry contract | adopted contract |
| Grafana Alloy | edge collector | preferred candidate |
| Alertmanager | alert routing | preferred candidate |
| restic | backup | preferred candidate |
| OpenBao | distributed secrets | optional candidate |
| Portainer | administration UI | not suitable for rootless baseline |
| Harbor | private registry | watchlist |
| MinIO | object storage | deferred to C3 |

No software is globally selected by this matrix. Each role remains subject to version, licence, security, performance and rollback gates.
