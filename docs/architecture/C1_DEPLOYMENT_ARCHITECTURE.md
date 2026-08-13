# C1 Deployment Architecture

## Profiles

### Standalone

Default profile for one host. Rootless Podman Quadlet is the primary candidate because it integrates OCI containers with systemd while preserving a simpler operational model than Kubernetes. Docker Compose remains an interoperability target, not a separate feature set.

### Cluster

K3s/Kubernetes is optional. It must not become a prerequisite for a single-node installation. The profile must preserve service contracts, health semantics, secret references, evidence paths and rollback behavior from standalone.

### Cloud / batch

OpenTofu, cloud-init/Ansible and a workload scheduler such as SkyPilot are candidates. Every job remains governed by the MARKET-OS WorkloadContract, data rights, budget, checkpoint and destruction receipt.

## Service Boundaries

- control plane and cockpit;
- data ingestion and data quality;
- canonical data fabric;
- research/replay/simulation;
- model and agent gateway;
- numerical truth kernel;
- portfolio/risk;
- execution adapters;
- memory/RAG;
- observability and notifications.

Each service receives least privilege, bounded resources, explicit network targets and an immutable image digest.

## Candidate Complete Applications

Evaluate before rebuilding:

- Grafana/Prometheus or Mimir/Loki/Tempo/OpenTelemetry/Alloy;
- Portainer only for administration value, never as the source of deployment truth;
- OpenBao for secret references and encryption services;
- MinIO or compatible object storage;
- Harbor for OCI registry and policy;
- JupyterHub for controlled research workspaces;
- Langfuse for model traces where data policy permits;
- n8n only for non-critical automation;
- Open WebUI, Dify, RAGFlow, Onyx and similar products only after security and architectural fit analysis.

## Current Decisions

- Grafana Agent is excluded as a new dependency because it reached end-of-life; Grafana Alloy is the candidate successor.
- OpenTelemetry remains the vendor-neutral telemetry contract.
- The standalone profile must work without K3s.
- No candidate is adopted by this document.
