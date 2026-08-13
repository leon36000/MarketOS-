---
artifact_id: ART-06B-CLAUDE-CODE-CONTRACT-001
version: "0.23.0"
date: 2026-08-04
phase: "06B"
status: "DESIGN_ONLY"
---

# Phase 06B Trading Tool Gateway & GUI Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans; every adapter begins with contract tests and hostile fixtures.

**Goal:** exposer logiciels et bibliothèques financières aux agents via outils typés, permissions minimales et preuves, avec GUI automation uniquement en VM isolée.

**Architecture:** Policy Enforcement Point central, registry versionné, adapters API/MCP/CLI/GUI, sandbox par session et audit append-only. Aucun outil n'accède directement au broker live ou au Risk Kernel.

**Tech Stack:** Python 3.13/Pydantic/FastAPI; MCP SDK candidate; gRPC/OpenAPI clients; libvirt/KVM candidate for GUI VM; Holo 3.1 candidate only.

**Interfaces:** The phase produces `ToolDescriptor`, `ToolInvocation`, `PermissionDecision`, `ToolEvidence` and `ToolGateway.invoke()`; broker/live capabilities are structurally absent from GUI-sandbox adapters.

## Global Constraints

- `LIVE_FORBIDDEN` est la classe par défaut.
- API native prévaut sur GUI.
- Token passthrough MCP interdit; OAuth audience-bound et TLS requis.
- Les annotations serveur et sorties GUI sont non fiables jusqu'à validation.
- Chaque side effect est déclaré, idempotent ou compensable.

### Task 1: Tool contracts and registry
**Files:** `runtime/tools/contracts.py`, `registry.py`, tests.
- [ ] Tests RED pour outil sans schema/version/side-effect/permission.
- [ ] Implémenter registry immutable-versioned et dependency graph.
- [ ] Vérifier disable/delete et historique reproductible.

### Task 2: Policy Enforcement Point
**Files:** `runtime/tools/policy.py`, `audit.py`, tests.
- [ ] Tester escalade de permission, data-class violation, secret misuse et rate limit.
- [ ] Implémenter deny-by-default, allowlist et audit hashé.
- [ ] Ajouter un veto absolu sur broker live, Risk Kernel et vault raw secret.

### Task 3: Deterministic finance adapters
**Files:** `runtime/tools/adapters/quantlib.py`, `qlib.py`, `openbb.py`, tests.
- [ ] Définir des sorties typées avec unités, dtype, version et diagnostics.
- [ ] Comparer les valeurs critiques au CPU Golden Oracle.
- [ ] Conserver exceptions et divergences comme preuves.

### Task 4: Engine adapters
**Files:** adapters LEAN/Nautilus/hftbacktest; tests paper/sandbox only.
- [ ] Tester versions, configs, data cutoffs et no-live route.
- [ ] Produire manifests de replay/backtest et importer uniquement résultats vérifiés.
- [ ] Vérifier qu'un résultat marketing ou benchmark interne n'est pas promu.

### Task 5: MCP gateway
**Files:** `runtime/tools/mcp/*`, tests security.
- [ ] Test RED pour token passthrough, wrong audience, HTTP clair et tool injection.
- [ ] Implémenter client/server adapters avec schemas locaux et permission mapping.
- [ ] Ignorer les annotations non vérifiées du serveur.

### Task 6: CLI sandbox
**Files:** `runtime/tools/cli_sandbox.py`, seccomp/container profiles, tests.
- [ ] Tester filesystem, réseau, timeout, output size et command allowlist.
- [ ] Exécuter en container éphémère; aucun shell libre fourni au modèle.

### Task 7: GUI sandbox with Holo 3.1
**Files:** `runtime/tools/gui/*`, `deployment/gui-sandbox/*`, tests.
- [ ] Créer VM snapshot non privilégiée, réseau allowlist et compte sans secret.
- [ ] Tester prompt injection visuelle, changement de layout, timeout et takeover.
- [ ] Enregistrer vidéo, screenshots, événements et exports en quarantaine.
- [ ] Interdire broker, secret entry, Risk Kernel et live.

### Task 8: Qualification
- [ ] Comparer API vs MCP vs CLI vs GUI sur exactitude, coût, latence et incidents.
- [ ] Simuler tool outage, corrupt output et partial side effect.
- [ ] Produire un rapport par outil, pas une adoption globale.

## Exit Gate

`06B_TOOL_GATEWAY_LOCAL_GATE_PASS` exige registry, PEP, audit, sandbox et preuves de non-accès live. Les logiciels propriétaires nécessitent licence et API écrites avant usage.

## Rollback

Désactiver adapters, détruire VMs/snapshots, révoquer tokens, conserver audit et restaurer le registry précédent.
