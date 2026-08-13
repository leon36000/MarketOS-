# C1 Evidence Ledger

## Primary evidence families

Podman rootless and Quadlet, K3s requirements, OpenTelemetry Collector security, Grafana Alloy and Agent EOL, Alertmanager routing and HA semantics, Loki retention, Tempo storage, OpenBao KV/AppRole/Transit, systemd credentials, restic, notifications, private-overlay access and registry candidates.

## Reproduced failure

### FAIL-C1-001 — non-idempotent derived manifest

- **Observed:** after regeneration, a second `--check` still reported the manifest stale.
- **Cause:** the manifest hashed old requirement/phase index bytes before writing the new derived contents.
- **Correction:** manifest generation now accepts expected-content overrides and hashes the bytes that will be written.
- **Regression:** `test_regeneration_repairs_manifest_and_indexes` passes in run `31739921853`.

## Negative findings retained

- Portainer does not fit the rootless Podman baseline documented for MARKET-OS.
- Grafana Agent is EOL and is excluded.
- Alloy's experimental OTel engine is excluded from the baseline.
- Alertmanager HA can deliver duplicate notifications; receivers must be idempotent.
- A backup without clean restoration remains unverified.
- K3s minimum resources do not establish MARKET-OS sizing.

## Unresolved

Exact versions, image digests, licences, signatures, resource budgets, compact-stack comparisons, identity-provider choice, object storage, final RPO/RTO and target-host tests remain open.
