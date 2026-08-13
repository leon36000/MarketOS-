# Phase 02B — Claude Code Execution Contract : Market Knowledge A→Z

> **For Claude Code:** execute task-by-task with TDD. This contract maps knowledge; it does not claim that markets are fully knowable.

**Goal:** transformer les 52 domaines de connaissance en ontologie, contrats, loaders, tests et matrices de couverture point-in-time.

## Global Constraints

- `live_trading_state=HARD_LOCKED`.
- `NO_FALSE_EXHAUSTIVENESS`: aucun domaine ne devient complet par simple rédaction.
- Toute connaissance historique respecte `available_to_strategy_at`, les cutoffs de modèles, de mémoire, d'embeddings et de corpus.
- Les sources, contradictions, inconnues, tests et conditions de réouverture sont obligatoires.

## Files

```text
runtime/knowledge/domain_contracts.py
runtime/knowledge/ontology.py
runtime/knowledge/coverage_ledger.py
runtime/knowledge/context_pack.py
runtime/knowledge/contradiction_registry.py
runtime/knowledge/unknown_registry.py
tests/knowledge/test_domain_contracts.py
tests/knowledge/test_temporal_visibility.py
tests/knowledge/test_coverage_ledger.py
tests/knowledge/test_contradictions.py
research/knowledge_domains/KDOM-*.md
```

## Task 1 — Domain contracts

**Files:** create `runtime/knowledge/domain_contracts.py` and test `tests/knowledge/test_domain_contracts.py`.

- [ ] Write tests that reject missing mechanism, source, falsification rule, phase owner and status.
- [ ] Run `python -m pytest tests/knowledge/test_domain_contracts.py -q`; expected RED because the module is absent.
- [ ] Implement immutable `KnowledgeDomainContract`, `KnowledgeClaim` and typed statuses.
- [ ] Run the same command; expected GREEN.

## Task 2 — Temporal knowledge visibility

**Files:** create `runtime/knowledge/context_pack.py` and test `tests/knowledge/test_temporal_visibility.py`.

- [ ] Write tests proving that a future filing, model weight, memory episode or embedding cannot enter an older context pack.
- [ ] Run `python -m pytest tests/knowledge/test_temporal_visibility.py -q`; expected RED.
- [ ] Implement dual-time filters plus model/memory/corpus cutoffs.
- [ ] Re-run; expected GREEN.

## Task 3 — Coverage and unknowns

**Files:** create `runtime/knowledge/coverage_ledger.py`, `runtime/knowledge/unknown_registry.py`, and test `tests/knowledge/test_coverage_ledger.py`.

- [ ] Test all 52 `KDOM-*` IDs, allowed state transitions, evidence minimums and reopen conditions.
- [ ] Test that `A_TO_Z_COMPLETE` is rejected while any domain is below `DECIDED`.
- [ ] Run RED, implement, then GREEN.

## Task 4 — Contradictions and ontology

**Files:** create `runtime/knowledge/ontology.py`, `runtime/knowledge/contradiction_registry.py`, and test `tests/knowledge/test_contradictions.py`.

- [ ] Test that facts, hypotheses and predictions cannot silently collapse into one status.
- [ ] Test conflicting sources, temporal supersession and unresolved contradiction gates.
- [ ] Implement the minimum ontology and contradiction graph required by the tests.

## Task 5 — Domain dossiers and qualification

- [ ] Create one `research/knowledge_domains/KDOM-*.md` dossier per domain from the canonical 52-domain ledger.
- [ ] Execute `python -m pytest tests/knowledge -q`.
- [ ] Execute `python tools/validate_release_v022.py .`.
- [ ] Produce a machine-readable coverage report with counts by state, missing primary sources, missing baselines and open contradictions.

## Exit Gate

`02B_KNOWLEDGE_COVERAGE_LOCAL_PASS` requires all 52 IDs present, temporal tests passing, and every domain at least `EVIDENCED`. This gate does not prove that the market has no unknowns.

## Rollback

Delete only the files listed by the 02B delta, restore the prior Current State and regenerate the RAG. Run `python tools/validate_release_v022.py .`; it must return PASS for the restored release.
