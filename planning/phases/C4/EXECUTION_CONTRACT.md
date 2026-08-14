# C4 — Claude Code Execution Contract

## Objective
Implement engine-neutral event, clock, replay, OMS/EMS, FIX-session, durable-distribution and visual-tool boundaries without opening a live route.

## Required surfaces
`runtime/events`, `runtime/time`, `runtime/bus`, `runtime/execution`, `runtime/workflows`, `runtime/tools/visual_bridge.py`, tests and benchmarks.

## TDD sequence
1. Equal timestamps still produce stable total order.
2. Backwards wall clock cannot corrupt durations.
3. Duplicate delivery leaves business state unchanged.
4. Crash after external effect reconciles before retry.
5. Lost FIX sequence recovers before new application flow.
6. Expired signed intents are rejected.
7. Candidate engines reproduce common replay fingerprints before speed comparison.
8. Changed GUI layout/postcondition aborts visual action.

## Qualification boundary
Local fixtures cannot adopt an engine, bus, broker or GUI route. Counterparty certification, target latency, real reconciliation and visual paper trials are separate gates.

## Rollback
Disable adapters/workflows, revoke temporary credentials, preserve event evidence, restore registry and prove live remains hard locked.
