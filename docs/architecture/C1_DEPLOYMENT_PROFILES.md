# C1 — Deployment Profiles

## Baseline decision

The mandatory profile is a single Linux host using rootless Podman Quadlet and systemd user services. Kubernetes is optional and cannot become a prerequisite for standalone use.

## P0 — standalone-core

- rootless Podman Quadlet;
- cgroup v2;
- local container storage;
- private ingress only;
- declarative container, network and volume units;
- images referenced by immutable digest;
- signature, SBOM and vulnerability evidence before promotion;
- tested start, stop, restart, uninstall and rollback.

P0 must support control, data, memory, research, numerical baseline, non-live risk and observability without Kubernetes.

## P1 — standalone-accelerated

Extends P0 with only the devices and runtimes admitted for a workload by the future Compute Fabric qualification. Drivers and firmware remain host-managed.

## P2 — cluster-k3s

Optional profile for measured multi-node, high-availability or device-scheduling needs. It must preserve the same service schemas, financial locks, secret-reference semantics, health meanings, telemetry and rollback behavior as P0.

## P3 — existing batch cluster

Integrates an existing batch scheduler. MARKET-OS submits bounded workload contracts and preserves its own evidence, checkpoints and cost records. C1 does not install or administer the external scheduler.

## P4 — temporary cloud capacity

Admission requires data rights, immutable images, cost and egress limits, encryption, a tested checkpoint, automatic expiry, a destruction receipt and local revalidation of critical results.

## Parity gate

A profile that cannot provide a mandatory behavior is `NOT_ADMITTED` for that role. Docker Compose may be generated for developer compatibility, but generated output cannot become a second source of truth.

## Supply chain

No mutable tags. Record image digest, source revision, licence, SBOM, vulnerability evidence and rollback instructions. Support offline export/import for critical artifacts.
