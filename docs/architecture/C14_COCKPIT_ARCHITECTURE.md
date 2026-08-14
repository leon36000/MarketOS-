# C14 — Premium Cockpit Architecture

The cockpit is a private local-first PWA backed by typed server APIs. It visualizes and proposes operations; authoritative data, numerical, risk, accounting and execution decisions remain server-side.

Views include command centre, markets, portfolio, risk, strategy/replay, agents/models, compute/cloud, tools, memory, evidence, incidents and settings. Each screen uses shared domain contracts rather than screen-specific financial logic.

The browser receives least-privilege session capabilities. There is no broker credential, raw provider key, risk-signing key or direct broker route in client code. Network access is private by default.

The interface supports optimistic presentation only for non-authoritative UI state. Financial and configuration mutations wait for a server receipt and postcondition verification.
