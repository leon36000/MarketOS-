# C1 — Claude Code Execution Contract

## Objective

Produce an executable deployment and operability design for MARKET-OS with a simple standalone profile, an optional cluster profile and a cloud/batch extension, without weakening functional parity or financial safety locks.

## Scope

- Rootless standalone deployment with Podman Quadlet or equivalent OCI tooling.
- Optional K3s/Kubernetes profile after standalone parity is proven.
- OpenTelemetry-compatible metrics, logs and traces.
- Alerts, notifications, runbooks, backup/restore and secret references.
- Evaluation of complete self-hosted applications before rebuilding equivalent internal systems.

## Out of Scope

- Live trading.
- Broker credentials.
- Driver, firmware or FPGA bitstream installation.
- Selecting a final database, observability backend or secret manager without benchmark evidence.

## Required Files

- `deployment/standalone/`
- `deployment/k3s/`
- `deployment/cloud/`
- `observability/otel/`
- `observability/alerts/`
- `runbooks/`
- `config/examples/`
- `tests/deployment/`
- `phases/C1/`

## Interfaces

### ServiceManifest

Must identify service ID, image digest, network policy, volumes, secret references, health checks, resource bounds, dependencies and recovery behavior.

### ObservabilityEnvelope

Must carry correlation IDs from source data through model, decision, risk, order, fill, reconciliation and outcome.

### AlertPolicy

Must define severity, deduplication key, receiver, acknowledgement, escalation, silence policy, runbook and evidence retention.

## TDD Sequence

1. RED: reject mutable image tags, plaintext secrets, missing health checks and unbounded resources.
2. GREEN: validate immutable OCI service manifests.
3. RED: reject standalone/cluster configuration divergence for mandatory behavior.
4. GREEN: add a parity validator.
5. RED: reject alerts lacking deduplication, receiver, runbook or escalation.
6. GREEN: implement alert-policy validation.
7. RED: demonstrate backup without tested restore is insufficient.
8. GREEN: implement restore drill and signed receipt.

## Verification Commands

```bash
python -m unittest discover -s tests -v
python tools/validate_repository.py --root . --json
podman kube play --down deployment/standalone/generated.yaml || true
```

Environment-specific commands remain `NOT_RUN` until their dependencies and target node are available.

## Failure Injection

- dependency unavailable;
- stale secret reference;
- container crash loop;
- disk full;
- time skew;
- network partition;
- missing telemetry backend;
- duplicate alert storm;
- corrupted backup;
- restore to a clean host.

## Exit Gate

C1 may progress only when:

- standalone deployment can be installed and removed without secrets left behind;
- cluster profile preserves mandatory behavior;
- observability correlation is end-to-end;
- alert and notification policies are deterministic and auditable;
- backup and clean-host restore are demonstrated;
- all exact versions, licenses, hashes and rollback instructions are recorded;
- minority findings and unresolved unknowns are preserved.

## Rollback

Stop services, revoke temporary credentials, remove rootless units and ephemeral state, restore the last verified configuration, verify the manifest and record a rollback receipt. No database or retained evidence is deleted without a separately approved retention action.
