# C1 — Service Topology and Trust Boundaries

## Design objective

MARKET-OS is decomposed into services with explicit authority, data classes and network reach. Containerization is a lifecycle and isolation mechanism; it is not proof of security or correctness.

## Planes

| Plane | Services | Authority boundary |
|---|---|---|
| Control | cockpit API, configuration, provider registry, scheduler API | configuration proposals only; cannot bypass risk |
| Data | ingestion, quality, security master, canonical fabric | authoritative observations only after provenance and temporal gates |
| Research | notebooks, feature builders, replay, backtests, world-model lab | no broker route; synthetic and real namespaces separated |
| Intelligence | model gateway, MOA, premium council, memory retrieval | advisory; no numerical or financial authority |
| Numerical | CPU Golden Oracle and admitted accelerators | numerical authority for declared workloads |
| Portfolio/Risk | investment book, optimizer, deterministic Risk Kernel | veto and sizing authority |
| Execution | OMS/EMS and broker adapters | isolated; accepts only signed and unexpired intents |
| Memory/Evidence | canon, Neon index, raw evidence, decision ledger | preserves source, time, version, contradictions and invalidations |
| Operations | telemetry collectors, metrics, logs, traces, alerts, backup | observes and recovers; cannot mutate financial policy |

## Network zones

```text
private_ingress
  -> control_zone
  -> data_zone
  -> research_compute_zone
  -> intelligence_zone
  -> numerical_zone
  -> risk_zone
  -> execution_zone

operations_zone observes all zones through explicit telemetry endpoints.
```

- Public ingress is disabled by default.
- Remote administration uses local access or a private overlay.
- The execution zone has an egress allowlist limited to approved broker and market endpoints.
- Research, GUI automation and world-model services have no route to broker credentials.
- Database and object-storage ports are internal only.
- Egress is deny-by-default and declared per service.

## Service manifest requirements

Every service declares:

- stable service ID and role;
- immutable OCI image digest and signature policy;
- CPU, RAM, storage and accelerator bounds;
- user, Linux capabilities and sandbox policy;
- allowed networks and egress targets;
- secret references, never raw values;
- health, readiness and dependency checks;
- data classifications and retention;
- telemetry and audit outputs;
- backup, restore and rollback behavior;
- versioned configuration hash.

## Privilege policy

- Rootless containers are the standalone default.
- Privileged containers, host PID, broad device mounts and container-engine sockets are forbidden unless a separate exception is reviewed and time-bounded.
- A model or GUI agent never receives a container-engine socket.
- Hardware access is granted per workload through the future Node Pack capability registry.

## Failure behavior

Unknown dependency state, stale configuration, missing secret, missing telemetry or failed integrity check produces `NOT_READY` or `QUARANTINED`, never silent degraded financial authority.
