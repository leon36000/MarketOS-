# C16 — Claude Code Execution Contract

## Objective
Perform the final cross-audit of the design plan, verify all 108 requirements and 16 design phases, publish the 49-node implementation DAG and build a deterministic Claude Code/Codex handoff archive.

## Required surfaces
`implementation/IMPLEMENTATION_DAG.json`, final handoff documents, `tools/validate_c16_design.py`, `tools/build_claude_pack.py`, pack tests, manifests, SBOM and clean-extraction verification.

## Test-first sequence
1. Missing validator and pack artifacts must fail before implementation.
2. Every requirement ID in the reconciled crosswalk must appear exactly once in the global audit set.
3. All 16 design phases must be `DESIGN_GATE_PASS`; all implementation nodes remain `NOT_STARTED`.
4. The DAG must contain exactly 00–40 and PC0–PC7, reference only existing dependencies and remain acyclic.
5. Live/profitability/implementation claims cannot be strengthened by packaging metadata.
6. The pack contains only tracked files plus generated root metadata, never `.git`, caches, credentials or transient outputs.
7. A deterministic rebuild from the same commit and `SOURCE_DATE_EPOCH` produces the same SHA-256.
8. A fresh extraction verifies file hashes, repository contracts and C16 contracts without network access.

## Exit gate

`C16_DESIGN_AND_BUILD_PACK_GATE_PASS` requires all tests, exact requirement coverage, acyclic DAG, deterministic archive reproduction and clean extraction. It proves the design handoff only, not MARKET-OS implementation, strategy edge, profitability or live readiness.

## Rollback

Remove the C16-generated archive and metadata, restore C15 Current State, retain the audit failure and rebuild only after root cause and validator repair.
