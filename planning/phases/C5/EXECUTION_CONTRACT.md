# C5 — Claude Code Execution Contract

## Objective
Implement a signed Node Pack, capability registry and workload-specific resource broker for local, remote and cloud CPU/GPU/RAM/NVMe/network/FPGA resources without assuming compatibility or numerical correctness.

## Required surfaces
`node-agent/api`, inventory, diagnostics and executor; `runtime/compute/contracts.py`, capability registry, resource broker, adapters, tests and benchmarks.

## TDD sequence
1. User-reported inventory cannot close runtime gates.
2. Capability states progress sequentially and expire.
3. Unmet precision, memory, rights or isolation constraints block scheduling.
4. Accelerated outputs fail when they change oracle decisions.
5. OOM, node loss, thermal throttling, accelerator reset and corrupt checkpoints fail cleanly.
6. Cloud budget, region, rights, TTL and destruction receipts are enforced.
7. FPGA cannot progress to purchase or canary before lower-stage economic evidence.

## Qualification
Each workload receives ADMIT, QUARANTINE or NOT_RUN per node/backend. No global hardware winner is produced. Drivers, firmware and bitstreams remain human-controlled.

## Rollback
Revoke node certificates, cancel jobs, destroy temporary cloud resources, remove agent services and prove no secret, allocation or workload remains active.
