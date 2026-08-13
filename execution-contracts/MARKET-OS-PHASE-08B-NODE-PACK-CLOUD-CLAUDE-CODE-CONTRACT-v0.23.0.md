---
artifact_id: ART-08B-CLAUDE-CODE-CONTRACT-001
version: "0.23.0"
date: 2026-08-04
phase: "08B"
status: "DESIGN_ONLY"
---

# Phase 08B Compute Node Pack & Cloud Fabric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. TDD and signed evidence are mandatory.

**Goal:** construire un agent léger installable sur chaque machine, capable d'inventorier, diagnostiquer et exécuter des WorkloadContracts sur CPU/GPU/RAM/NVMe/FPGA/RDMA, plus une lane cloud à budget borné.

**Architecture:** agent Go 1.26.x signé, gRPC mTLS, systemd + Podman Quadlet rootless par défaut; adaptateurs facultatifs K3s, Slurm et cloud. MARKET-OS central conserve le Capability Registry et le Resource Broker.

**Tech Stack:** Go 1.26.x exact locked; protobuf/gRPC; SQLite local; cosign/Sigstore candidate; hwloc; vendor tools; Podman 5.7+ candidate; Ansible; OpenTofu; SkyPilot optional.

**Interfaces:** The phase produces `NodeIdentity`, `SignedInventory`, `WorkloadContract`, `CapabilityRegistry`, `ResourceBroker.schedule()` and cloud `ProvisioningReceipt`; all later schedulers consume only these typed outputs.

## Global Constraints

- Aucun driver, firmware ou bitstream installé automatiquement.
- Mot de passe SSH uniquement bootstrap, jamais persisté.
- Inventaire utilisateur = `USER_REPORTED` jusqu'au probe signé.
- Un workload est planifié seulement si tous les hard constraints sont vrais.
- Les nœuds de calcul ne reçoivent pas de secret broker/live.
- FPGA reste `WATCHLIST_CONDITIONAL_NO_PURCHASE`.

### Task 1: Protocoles et identité de nœud

**Files:** `node-agent/api/node.proto`, `node-agent/internal/identity/*`, `tests/node_agent/test_enrollment.py`.

- [ ] Écrire les tests RED pour token expiré, certificat wrong-node, replay et rotation.
- [ ] Générer les stubs et implémenter enrôlement mTLS avec identité stable.
- [ ] Vérifier révocation et renouvellement sans réutiliser le mot de passe SSH.

### Task 2: Inventory Probe

**Files:** `node-agent/internal/inventory/*`, `runtime/compute/node_inventory.py`, tests fixtures Linux/NVIDIA/AMD/Intel.

```go
type CapabilityState string
const (
    Present CapabilityState = "PRESENT"
    DriverReady CapabilityState = "DRIVER_READY"
    SDKReady CapabilityState = "SDK_READY"
    DiagnosticPass CapabilityState = "DIAGNOSTIC_PASS"
    Benchmarked CapabilityState = "BENCHMARKED_FOR_ROLE"
)
```

- [ ] Tests RED pour cgroup visible/effectif, NUMA, PCI topology, stale inventory et outil homonyme hostile.
- [ ] Implémenter collectors hwloc/sysfs/vendor avec chemin, version et SHA-256 des outils.
- [ ] Signer l'inventaire normalisé et conserver les sorties brutes.

### Task 3: Diagnostics vendors

**Files:** `node-agent/internal/diagnostics/nvidia.go`, `amd.go`, `intel.go`, `fpga.go`.

- [ ] Tests RED pour DCGM absent, AMD SMI partiel, oneAPI incompatible, FPGA sans toolchain.
- [ ] Implémenter probes read-only et mapper les résultats sans extrapolation.
- [ ] Ajouter burn-in/PCIe/memory/collectives comme jobs explicites, jamais au probe léger.

### Task 4: Workload executor et isolation

**Files:** `node-agent/internal/executor/*`, `runtime/compute/workload_contract.py`.

- [ ] Test RED : image non digestée, mémoire insuffisante, réseau non allowlisté, checkpoint manquant.
- [ ] Implémenter rootless Podman Quadlet, cgroups v2, affinity et scratch éphémère.
- [ ] Hash inputs/outputs, capturer ressources, énergie et logs.
- [ ] Injecter OOM, kill -9, disque plein et redémarrage; checkpoint ou échec propre.

### Task 5: Capability Registry et Resource Broker

**Files:** `runtime/compute/capability_registry.py`, `resource_broker.py`, tests.

- [ ] Tests RED pour stale health, oversubscription, incompatible precision/backend et contention LLM/math.
- [ ] Implémenter hard filters puis score localité/coût/temps/énergie.
- [ ] Vérifier fallback CPU oracle et quarantaine workload-specific.

### Task 6: Bootstrap packs

**Files:** `deployment/node-pack/ansible/*`, `cloud-init.yaml`, `install.sh`, `uninstall.sh`, tests Molecule/container.

- [ ] Test de dry-run sur Ubuntu Server 24.04 et rollback complet.
- [ ] Créer utilisateur, directories, systemd/Quadlet et certificate enrollment.
- [ ] Interdire toute modification driver/firmware sans flag séparé et approbation.

### Task 7: K3s et Slurm adapters

**Files:** `runtime/compute/adapters/k3s.py`, `slurm.py`, tests.

- [ ] Tester device resources, cgroups, Slurm GRES, accounting, output manifest et cancellation.
- [ ] Ne pas installer K3s/Slurm; seulement intégrer les environnements existants.
- [ ] Vérifier que la lane standalone reste fonctionnelle sans eux.

### Task 8: Cloud adapter

**Files:** `runtime/compute/adapters/opentofu.py`, `skypilot.py`, `deployment/cloud/*`, tests.

- [ ] Tests RED pour lock absent, image tag mutable, budget nul, licence local-only et checkpoint non restaurable.
- [ ] Implémenter plan/apply/destroy wrappers avec state locking et journal de coût.
- [ ] SkyPilot reste optional; vérifier les limites Slurm et les checkpoints applicatifs.

### Task 9: Qualification cible

**Files:** `benchmarks/08B/*`, `phases/08B/MARKET-OS-PHASE-08B-RESULTS.json`.

- [ ] Exécuter inventaire signé sur chaque nœud réel.
- [ ] Benchmarker CPU oracle, Monte-Carlo, PIT joins, L2 replay, LLM inference, collectives et storage.
- [ ] Mesurer cold/warm, énergie, thermals, ECC/RAS et soak.
- [ ] Produire rôle par rôle `ADMIT`, `QUARANTINE` ou `NOT_RUN`; aucun classement global naïf.

## Exit Gate

`08B_NODE_PACK_TARGET_GATE_PASS` exige installation/rollback, mTLS, inventaire signé, isolation, diagnostics et benchmarks sur les machines réelles. Une fixture ou un conteneur ne ferme pas la gate.

## Rollback

Révoquer certificats, annuler jobs, détruire ressources cloud, supprimer Quadlets et utilisateur de service, restaurer configs et vérifier qu'aucun secret/artifact n'est laissé.
