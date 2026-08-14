# C13 — Claude Code Execution Contract

## Objective
Implement exact authoritative books, constrained portfolio optimization, an independent deterministic Risk Kernel, broker capability/adapters, exact accounting, security controls and recovery.

## Required surfaces
`runtime/books`, `runtime/portfolio`, `runtime/risk`, `runtime/brokers`, `runtime/accounting`, `runtime/security`, tests and failure drills.

## TDD sequence
1. A model, strategy or optimizer cannot override a risk veto.
2. Unreconciled cash, position or execution state blocks risk-increasing intents.
3. Unknown or expired broker capability denies the operation.
4. Exact double-entry cash/lots/PnL/fees/FX/corporate actions reconcile from events.
5. Duplicate, late and contradictory broker events remain idempotent and auditable.
6. Stale data/clock, position divergence and risk-service failure trigger deterministic halt/cancel policy.
7. Secret values never enter repository, browser readback, telemetry or model context.
8. Supply-chain tampering, credential loss, storage corruption and node loss exercise recovery and rollback.

## Qualification boundary
Local fixtures cannot select a broker, solver or secret manager and cannot qualify production risk or live trading.

## Rollback
Revoke routes and credentials, cancel safe-to-cancel orders, restore reconciled books and previous signed policies, preserve audit evidence and prove live remains hard locked.
