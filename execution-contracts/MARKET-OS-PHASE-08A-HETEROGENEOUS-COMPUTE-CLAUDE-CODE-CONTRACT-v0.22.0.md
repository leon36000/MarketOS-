# Phase 08A — Claude Code Execution Contract : Heterogeneous Compute & FPGA Feasibility

> **For Claude Code:** use TDD and measured target facts. No reported hardware specification may be promoted without a signed runtime probe.

**Goal:** inventorier réellement l’infrastructure, construire un scheduler de charges prouvable et qualifier CPU/GPU/RAM/NVMe/réseau/cloud/FPGA sans adoption prématurée.

## Files

```text
runtime/compute/contracts.py
runtime/compute/inventory_probe.py
runtime/compute/capability_registry.py
runtime/compute/resource_broker.py
runtime/compute/slurm_adapter.py
runtime/compute/k3s_adapter.py
runtime/compute/runtime_adapters/dask.py
runtime/compute/runtime_adapters/ray.py
runtime/compute/runtime_adapters/mpi_ucx.py
runtime/compute/fpga_admission.py
benchmarks/08A/workloads/*.py
benchmarks/08A/run_qualification.py
tests/compute/*.py
```

## Task Sequence

**Files:** create `runtime/compute/contracts.py`, `runtime/compute/inventory_probe.py`, `runtime/compute/capability_registry.py`, `runtime/compute/resource_broker.py`, scheduler/runtime adapters, `runtime/compute/fpga_admission.py`, `benchmarks/08A/run_qualification.py`, and tests under `tests/compute/`.

1. **Inventory schema:** write `tests/compute/test_inventory.py`; observe RED; implement CPU topology/flags, RAM, NUMA, GPU/NPU, NVMe, NIC, PCIe, drivers, firmware, thermals and cgroups; observe GREEN.
2. **Signed capability registry:** test raw command hashes, normalized inventory, expiry and stale-health rejection before implementing `capability_registry.py`.
3. **WorkloadContract:** test precision, determinism, data class, resources, SLO, fallback and evidence path.
4. **Resource broker:** test no-allocation on unmet hard constraints, oversubscription and stale health.
5. **Slurm lane:** generate dry-run `sbatch` with CPU/GPU/GRES, cgroups, memory, time, energy and output manifest; do not deploy Slurm before config audit.
6. **K3s lane:** constrain services and bounded jobs; test device assignment and cgroup/resource limits.
7. **Dask/Ray/MPI lane:** run an identical deterministic fixture and measure physical usage; `RAY_LOGICAL_RESOURCES_NOT_ISOLATION` remains enforced.
8. **UCX/RDMA lane:** probe transports, topology, correctness and TCP fallback.
9. **Cloud burst lane:** test data-rights, maximum-cost, immutable-image, checkpoint and local-revalidation gates.
10. **FPGA admission:** execute F0–F7 state transitions; default is `WATCHLIST_CONDITIONAL_NO_PURCHASE`.
11. **Benchmarks:** execute CPU golden oracle, Monte-Carlo, PIT joins, L2/L3 replay, local LLM and transfer fixtures.
12. **Faults:** inject OOM, thermal throttling, node loss, NIC error, GPU error, corrupt checkpoint and scheduler restart.

## Required Commands

```bash
python -m pytest tests/compute -q
python benchmarks/08A/run_qualification.py --config config/MARKET-OS-COMPUTE-FABRIC-TEMPLATE-v0.22.0.json --output-dir /tmp/marketos-08a
python tools/validate_release_v022.py .
python tools/validate_authorized_delta.py .
```

## Exit Gate

`08A_TARGET_INVENTORY_AND_ROLE_BENCHMARK_PASS` requires measurements on each actual target node, workload-specific numerical equivalence and fault tests. Container or user-reported data cannot close it. FPGA remains non-adopted unless `FPGA_ECONOMIC_ADMISSION_GATE` passes.

## Rollback

Remove only 08A runtime and benchmark files listed in the signed delta, restore previous scheduler configuration and Current State, stop any 08A-created services, and rerun `python tools/validate_release_v022.py .`. No FPGA bitstream or scheduler daemon may remain active after rollback.
