# PR14 → PR20 Architecture Reconciliation Audit

## Scope

This audit reconciles the C16 target architecture carried by PR #14 with the executable, stacked evidence in PR #15 through PR #20. It is governance-only: it does not merge PR #14, change trading/runtime behavior, select providers/backends, authorize capital, prove strategy edge, or alter live-trading authority.

## Primary findings

### PR14 is not current merge-safe canon

PR #14 exact head is `bd3bf2823d6e731ece5ed8d66570d196be42b560`. Its exact-head workflows failed:

- `validate` run `31761607472`: failure;
- `validate-c16` run `31761607461`: failure.

The C16 workflow stopped at `tools/regenerate_derived.py --check`, which reported stale `planning/PHASE_INDEX.json` and `MANIFEST.json`. C16 tests, cross-audit and pack verification were therefore skipped. The branch also lacks the C13–C15 design-gate chain required by its own C16 validator.

PR14 remains useful as a **target architecture source**, especially its 49-node dependency DAG and policy blocks on nodes 37–39. It is not evidence that C16 passed or that the deterministic pack was verified.

### PR15–PR20 are executable evidence slices, not completed DAG nodes

The executable chain is:

| PR | Exact head | Evidence role |
|---|---|---|
| 15 | `fab4c16c048e3216093a43af0c42f5f0c9562c33` | deterministic foundation/paper-core slice |
| 16 | `9b6f9d94de82963a62e07a6183d63cf1a5dea33a` | Security Master/Data Fabric slice |
| 17 | `e602c17e22caa12bf358743c47a38e90cdaeb8a9` | canonical market-data/bars slice |
| 18 | `ffe23f955770f68bf897f94c7a506dfeb27c09b6` | venue calendar/Feature Store slice |
| 19 | `ea851564a2a5781cd3627d0dd5eb9ca857001095` | research-governance/temporal-validation slice |
| 20 | `b05dd6004f60cc20b76c2c5c86c3ba6046401180` | execution calibration/shadow/capacity slice |

Each slice can overlap one or more broad PR14 target nodes. Overlap is recorded as `VERIFIED_PARTIAL`, never `COMPLETE`. A target node may become complete only after its complete exit contract is implemented and independently verified.

### Requirements have two distinct universes

The repository oracle contains **108 canonical requirements**. The MarketOS memory database currently contains **119 observed requirement rows**, including audit extensions and partial/missing items. The 119-row set is a useful audit superset but is not allowed to replace the 108-row repository oracle without explicit reconciliation.

### Closure-contract provenance drift is real

Persistent memory referenced C13/C14 closure-contract paths that do not exist on the verified PR20 tree. These references are recorded as unresolved and are forbidden as implementation evidence. A future Proof Engine must require every material closure reference to resolve to an exact repository path, blob/hash and source authority or fail closed.

## Critical open gaps

- `C13_RUNTIME_CONTRACTS`: full portfolio optimizer, production-independent Risk Kernel contract, broker/OMS/EMS boundaries, exact accounting, security/recovery and their tests remain incomplete at the broad target-node level.
- `C14_COCKPIT_AND_OPERABILITY`: candidate architecture exists separately, but cockpit/auth/configuration/observability/alerts/incidents are not implemented as a verified C14 slice.
- `C15_QUALIFICATION`: historical tournament, real-time shadow qualification, paper qualification, red-team readiness and any canary authorization remain unimplemented as broad qualification gates.
- `C16_PACKAGING_AND_INTEGRATION`: PR14 packaging claims are not verified at its exact head and need reconstruction only after prerequisites exist.
- `PROOF_BINDING`: claims, closure refs and memories need mechanical binding to exact SHA/CI/artifact/source authority.
- `REQUIREMENTS_119_VS_108`: audit-memory additions must be reconciled explicitly with the canonical 108-row oracle.

## TDD evidence for this reconciliation

The acceptance contract was committed before its verifier. GitHub Actions run `32190314878`, job `95882992607`, checked merge ref `a4fb9b542e4ef89dd4038704396105bb608ae3a1` and observed the expected RED:

`ModuleNotFoundError: No module named 'tools.verify_architecture_reconciliation'`

The one-shot RED workflow was removed after the log was captured. The permanent verifier and CI are introduced only after that proof.

## Hard boundaries

- `live_trading = HARD_LOCKED`
- `profitability = UNPROVEN`
- `software_implementation_complete = false`
- no broad PR14 implementation node is marked complete;
- PR14 remains ineligible as current canon at its failed exact head;
- no broker, strategy champion, solver, production backend or live route is selected.
