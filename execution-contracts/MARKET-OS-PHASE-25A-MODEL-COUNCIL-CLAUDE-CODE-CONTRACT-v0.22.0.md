# Phase 25A — Claude Code Execution Contract : Premium Model Council

> **For Claude Code:** build a measurable advisory council, never a voting authority. Provider aliases and unpinned `latest` IDs are forbidden in qualifying runs.

**Goal:** construire un conseil multi-fournisseurs mesurable qui améliore le plan sans transformer une majorité de LLM en autorité.

## Files

```text
runtime/council/contracts.py
runtime/council/model_discovery.py
runtime/council/model_registry.py
runtime/council/evidence_packet.py
runtime/council/blind_round.py
runtime/council/benchmark_weights.py
runtime/council/error_correlation.py
runtime/council/consensus.py
runtime/council/minority_report.py
runtime/council/claude_code_handoff.py
tests/council/*.py
benchmarks/25A/run_private_council_eval.py
```

## Task 1 — Exact model discovery

- [ ] Test exact provider/model ID, release/cutoff, retention and capability flags; reject `latest`.
- [ ] Run `python -m pytest tests/council/test_model_discovery.py -q`; expected RED.
- [ ] Implement provider adapters and immutable registry entries; re-run GREEN.

## Task 2 — EvidencePacket and blind first pass

- [ ] Test canonical hashing, redaction, allowed tools and forbidden claims.
- [ ] Test that no member sees another response before committing its own hash.
- [ ] Observe RED, implement the minimum, observe GREEN.

## Task 3 — Private benchmark and weights

- [ ] Build held-out tasks for architecture, finance, numerical reasoning, code, source verification, bug finding and abstention.
- [ ] Test that equal vote is rejected.
- [ ] Test calibration, task-specific OOS weights and residual-error-correlation penalty.

## Task 4 — Dissent, consensus and handoff

- [ ] Test hard-gate dissent veto, mandatory minority report and canon-over-consensus.
- [ ] Test that the council cannot enable live, select a provider or promote a strategy.
- [ ] Test the generated Claude Code handoff contains exact paths, commands, tests, rollback and unresolved assumptions.

## Task 5 — Fault and marginal-value tournament

- [ ] Test provider outage, model retirement, quota, malformed JSON, hallucinated citation and prompt injection.
- [ ] Execute `python -m pytest tests/council -q`.
- [ ] Execute the private held-out council benchmark using an exact locked config.
- [ ] Compare the council to the best single model across repeated runs; preserve cost, latency and dissent.

## Exit Gate

`25A_PRIVATE_COUNCIL_ADMISSION_PASS` requires at least ten active exact model IDs, four providers, one local model, repeated held-out runs, calibrated task weights, correlation penalty, no unresolved hard-gate dissent and a non-critical rehearsal. The council cannot enable live or promote a strategy.

## Rollback

Revoke temporary provider credentials, delete only 25A files named by the signed delta, restore the prior Current State and model registry, purge non-canonical response caches and rerun validation.
