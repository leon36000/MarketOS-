---
artifact_id: ART-26A-CLAUDE-CODE-CONTRACT-001
version: "0.23.0"
date: 2026-08-04
phase: "26A"
status: "DESIGN_ONLY"
---

# Phase 26A Selective Temporal Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans. Memory writes are security-sensitive and require RED tests first.

**Goal:** construire une mémoire sélective point-in-time qui apprend des succès, erreurs et incidents sans transformer les sorties LLM ou le hasard en faits.

**Architecture:** raw episodes immutable, temporal facts, graph adapter, episodic/procedural/negative memory, write-policy service and context assembler. Every authoritative write is versioned and provenance-bound.

**Tech Stack:** Python/Pydantic; PostgreSQL/Parquet baseline; Qdrant/pgvector and Graphiti/Neo4j/FalkorDB candidates behind ports; evaluation harness inspired by long-memory benchmarks.

**Interfaces:** The phase produces `EpisodeRecord`, `MemoryCandidate`, `MemoryDecision`, `TemporalMemoryQuery` and `MemoryStore.write_candidate()`; authoritative promotion requires an independent validator.

## Global Constraints

- Raw episodes and negative results are never deleted.
- Future memories are invisible to historical runs.
- Success requires attribution and counterfactual before lesson promotion.
- LLM output alone cannot become authoritative memory.
- Retrieval preserves contradictions and source confidence.

### Task 1: Memory schemas and temporal invariants
- [ ] Tests RED for missing event/knowledge time, source and hash.
- [ ] Implement Episode, FactVersion, LessonCandidate, ProceduralSkill and Incident.
- [ ] Property-test append-only corrections/retractions.

### Task 2: Immutable episode store
- [ ] Test content-addressed idempotence, tampering and replay.
- [ ] Store prompts/tool calls/visible data/decision/outcome with secret redaction.

### Task 3: Write policy and quarantine
- [ ] Test thresholds, malicious high confidence, source conflict and duplicate episode.
- [ ] Implement scoring and lifecycle transitions.
- [ ] Require independent validator for VERIFIED/MATURE.

### Task 4: Attribution and counterfactual lessons
- [ ] Test winning bad decision and losing good decision.
- [ ] Decompose signal, sizing, timing, costs, regime, execution and luck.
- [ ] Create lesson only with supported transfer conditions.

### Task 5: Temporal graph adapter
- [ ] Baseline in-memory graph; Graphiti/FalkorDB/Neo4j adapters later.
- [ ] Test node/edge validity, invalidation, historical queries and overwritten attributes.
- [ ] No graph backend becomes truth authority.

### Task 6: Selective retrieval/context assembler
- [ ] Test lexical/vector/graph fusion, temporal filters, diversity and token budget.
- [ ] Preserve raw pointers and construct query-time summaries.
- [ ] Test false premise and abstention.

### Task 7: Poisoning and privacy
- [ ] Inject prompt injection, malicious memory, stale lesson and cross-strategy leakage.
- [ ] Verify quarantine, source tracing and deletion/retraction policy.

### Task 8: Evaluation
- [ ] Benchmark static facts, dynamic updates, workflows, gotchas and premise awareness.
- [ ] Measure decision OOS benefit, not retrieval score alone.
- [ ] Produce false-positive/false-negative memory report and TCO.

## Exit Gate

`26A_SELECTIVE_MEMORY_LOCAL_GATE_PASS` requires temporal correctness, immutable raw episodes, quarantine, attribution and poisoning tests. It does not prove better trading decisions until OOS experiments pass.

## Rollback

Freeze writes, export append-only logs, restore previous policy/index versions, preserve raw and negative memory, and invalidate derived contexts.
