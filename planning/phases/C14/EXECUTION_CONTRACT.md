# C14 — Claude Code Execution Contract

## Objective
Implement a private premium cockpit that exposes evidence, uncertainty, configuration and operations without becoming a financial, secret or deployment authority.

## Required surfaces
`apps/cockpit`, typed backend APIs, configuration registry, evidence components, accessibility tests, browser security tests and end-to-end operational scenarios.

## TDD sequence
1. A material claim without source, freshness, uncertainty and gate state must not render as authoritative.
2. PnL cannot be displayed as proof of decision quality without attribution.
3. Secret entry returns only an opaque reference; readback and model/browser propagation fail.
4. Add, disable and delete flows require catalog diff and dependency analysis.
5. Sensitive mutations require strong reauthentication, typed reason, preview, server-side execution and audit receipt.
6. Browser code cannot call a broker or Risk Kernel authority route directly.
7. Mobile cannot increase risk, change limits, add secrets or promote models.
8. WCAG 2.2 AA, keyboard, focus, reflow, reduced motion and non-color status receive automated and manual tests.

## Qualification boundary
Local mocks cannot select a frontend, auth or secret platform and cannot prove target deployment, accessibility or security.

## Rollback
Disable the cockpit route, revoke sessions/tokens, restore signed configuration versions, preserve audit records and prove authoritative services remain independently controllable.
