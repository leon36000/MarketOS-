# C16 — Final Implementation Handoff

## Boundary

The design plan is complete only when C16 passes. The MARKET-OS software, providers, target hardware, strategy edge, profitability and live readiness remain unimplemented or unproven.

## Entry order

Claude Code begins at node `00` in `implementation/IMPLEMENTATION_DAG.json`, creates an isolated worktree, verifies repository contracts and completes only nodes whose dependencies and gates pass. PAPER-CORE nodes PC0–PC7 provide an early vertical thread without bypassing the main phases.

## Mandatory workflow per node

1. Read authority, Current State, node contract and requirement subset.
2. Retrieve bounded Neon/file evidence and create a read receipt.
3. Write RED tests and hostile fixtures before implementation.
4. Implement the smallest contract-compliant change.
5. Run unit, property, integration, security, performance and rollback tests appropriate to the node.
6. Obtain independent review and minority findings.
7. Record exact versions, hashes, evidence, failures and open gates.
8. Update Current State and manifests only after verification.

## Agent authority

Claude Code orchestrates. Codex or another independent agent verifies critical changes. The premium council proposes and critiques but cannot override canon, Risk Kernel, hidden evaluators or live locks.

## Parallelism

Only nodes without unresolved dependency edges may run concurrently. Shared contracts, schemas, clocks, data identity, exact money and risk authority are serialized before dependent work.

## Completion semantics

A node is complete only when its declared artifacts, tests, target evidence, rollback and gate report pass. Documentation, local fixtures or model consensus cannot substitute for external/provider/target evidence.
