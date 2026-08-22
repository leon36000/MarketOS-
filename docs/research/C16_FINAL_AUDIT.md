# C16 — Final Cross-Audit Method

## Requirement audit

The reconciled CSV is the set oracle. The global C16 audit must contain the same 108 unique IDs. Phase closures, design artifacts and the final implementation DAG are checked for existence and consistency. Missing, duplicate or invented IDs fail.

## Phase audit

C1–C16 must each expose a decision/closure or equivalent gate record and `DESIGN_GATE_PASS`. A design pass cannot imply implementation, target, provider, financial or live qualification.

## DAG audit

Expected node IDs are exactly `00`–`40` plus `PC0`–`PC7`. Dependencies must exist, the graph must be acyclic and every node starts `NOT_STARTED`. Live-related nodes 37–39 remain policy-blocked.

## Claim audit

Machine-readable state, phase decisions, pack metadata and user-facing instructions are scanned for contradictions. The authoritative boundary is:

```yaml
software_implementation_complete: false
strategy_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

## Artifact audit

Critical contracts cannot contain unresolved `TODO`, `TBD`, dummy secrets or mutable model/image aliases. External candidates retain role-specific states rather than global adoption.

## Pack audit

Build twice, compare SHA-256, extract into an empty directory, validate every byte and run validators offline. Preserve the verification report, tool versions, commit and archive hash.
