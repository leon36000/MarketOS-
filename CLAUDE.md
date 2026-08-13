# MARKET-OS — Claude Code Instructions

## Authority
1. Direct owner directive.
2. Verified canon and hashes.
3. Approved delta.
4. Evidence and execution state.
5. Validated Neon memory.
6. Memory Vault.
7. Summaries.
8. Implicit model memory.

## Global invariants
- The current deliverable is the complete design plan, not a live trading system.
- `live_trading_state = HARD_LOCKED`.
- `profitability = UNPROVEN`.
- No phase is complete without requirement traceability, evidence, tests, adversarial checks,
  rollback, a gate report, and explicit unknowns.
- Do not introduce a dependency because it is popular or vendor-recommended.
- No secrets, credentials, tokens, or private keys may enter Git.
- Exact versions, image digests, licenses, SBOM and provenance are required before implementation.
- A model cannot validate its own output. Deterministic tools and an independent reviewer are required.
- Use a dedicated branch/worktree per phase.

## C1 rules
- Compose is the local-development profile.
- Rootless Podman Quadlet is the candidate default standalone operations profile.
- K3s is optional and must not be required for a one-host installation.
- OpenTelemetry semantic conventions are the telemetry contract.
- Application candidates remain `SCREENED`, `CORE_CANDIDATE`, `OPTIONAL_CANDIDATE`,
  `WATCHLIST`, `DEFERRED`, or `REJECTED_FOR_CORE` until a gate explicitly changes them.
- No mutable image tags in implementation manifests.
