# MARKET-OS — C1 Qualification

## Scope

C1 converts the deployment and operability requirements into explicit service, profile, telemetry, alerting, secret and recovery contracts.

## Decisions

- rootless Podman Quadlet is the mandatory standalone candidate;
- K3s is optional and requires parity plus measured multi-node value;
- OpenTelemetry/OTLP is the telemetry contract;
- Alertmanager is the preferred alert-routing candidate with at-least-once semantics;
- remote access is private by default;
- secret handling is split into bootstrap, standalone-runtime and distributed tiers;
- a backup is unverified until an isolated restore and hash/semantic checks pass;
- complete applications are evaluated before custom rebuilding;
- no software package is globally adopted in C1.

## Evidence boundary

The phase uses current official documentation to support architecture screening. It does not prove target-node compatibility, resource consumption, security, recovery time or operational value. Those claims remain implementation and target-test gates.

## Fresh controls

Machine-readable validation covers deployment profiles, ingress, secret readback, global adoption, telemetry correlation, alert delivery assumptions, restore requirements, requirement mapping and hard financial locks.

## Status

`CANDIDATE_PENDING_CI_AND_ADVERSARIAL_VERIFICATION`.
