---
artifact_id: ART-28A-CLAUDE-CODE-CONTRACT-001
version: "0.23.0"
date: 2026-08-04
phase: "28A"
status: "EXPERIMENTAL_DESIGN_ONLY"
---

# Phase 28A Recursive Improvement Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans. Candidate self-modification is confined to isolated branches.

**Goal:** comparer une boucle champion/challenger simple aux patterns DGM, HGM, HyperAgents et Polaris pour générer et évaluer des améliorations sans accès au système actif.

**Architecture:** immutable champion, candidate archive/tree, sandbox builder, fixed hidden evaluator, multi-stage financial gates and signed promotion proposal. The lab cannot modify risk, broker, live policy or canon.

**Tech Stack:** Python orchestration; isolated git worktrees/containers; Claude Code/model council as untrusted candidate generators; existing test/benchmark stack.

**Files:** Create `runtime/improvement/{contracts,archive,sandbox,evaluator,scheduler}.py`, `tests/improvement/`, `benchmarks/28A/`, and immutable evidence under `phases/28A/`.

**Interfaces:** The phase produces immutable `ChampionSnapshot`, `EvaluatorSnapshot`, `ImprovementProposal`, `ChallengerArtifact` and `RecursiveLab.run_budgeted_cycle()`; no interface can mutate champion, evaluator, canon, Risk Kernel or execution.

## Global Constraints

- Champion and evaluator are immutable during a tournament.
- Candidates cannot read hidden holdouts or evaluator code.
- No broker key, live endpoint, vault, Risk Kernel or production write mount.
- Online adaptation may update calibration/state, not active code/weights/prompts.
- Promotion remains human-signed initially and gate-driven.

### Task 1: Candidate and archive contracts
- [ ] Tests RED for mutable champion, duplicate lineage and missing parent.
- [ ] Implement Candidate, Modification, Evaluation and ArchiveNode.
- [ ] Preserve rejected candidates and failure reasons.

### Task 2: Baseline champion/challenger loop
- [ ] Generate bounded code/prompt/tool candidates from an approved request.
- [ ] Build in isolated worktree and OCI sandbox.
- [ ] Run unit, property, security and performance tests.

### Task 3: DGM-style archive scheduler
- [ ] Implement archive sampling based on verified performance and novelty.
- [ ] Test selection pressure, diversity collapse and reward hacking.
- [ ] Compare to random and simple best-first baselines.

### Task 4: HGM clades/metaproductivity lane
- [ ] Represent clades and measure downstream candidate productivity.
- [ ] Prevent a clade score from bypassing financial gates.
- [ ] Test computational budget fairness.

### Task 5: HyperAgents/Polaris lane
- [ ] Separate task agent and meta-agent editable policy.
- [ ] Limit editable surface through an allowlisted AST/config schema.
- [ ] Verify rollback and no evaluator mutation.

### Task 6: Financial evaluator
- [ ] Use hidden temporal holdout, walk-forward, PBO/DSR, costs, risk, calibration and regime tests.
- [ ] Evaluate NO_TRADE and resource/TCO.
- [ ] Reject any future-data or memory contamination.

### Task 7: Adversarial lab
- [ ] Test reward hacking, test deletion, metric gaming, secret access, network escape, infinite loop and artifact forgery.
- [ ] Require independent Completion Judge and signed evidence.

### Task 8: Promotion proposal
- [ ] Produce immutable diff, evidence, minority report, rollback and canary plan.
- [ ] Do not deploy; handoff to existing champion/challenger gate.

## Exit Gate

`28A_RECURSIVE_LAB_LOCAL_GATE_PASS` means the sandbox and evaluation are safe enough for research. Adoption requires demonstrated OOS advantage over the simple baseline and no gate bypass.

## Rollback

Destroy candidate worktrees/containers, revoke temporary credentials, retain archive/evidence, verify champion hash unchanged and restore scheduler state.
