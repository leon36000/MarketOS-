# C4 Trading Engine Bake-off

NautilusTrader is the preferred event-driven candidate. QuantConnect LEAN is the reference comparison candidate. A custom MARKET-OS core is a fallback only if measured gaps cannot be solved through adapters or upstream changes.

MARKET-OS owns the domain interfaces. Engine-native types do not escape their adapter boundary.

Each candidate must support deterministic replay, consistent replay/shadow/paper semantics, checkpoint and resume, explicit calendars and status, external-event versions, partial-state events, conservative cost models, evidence hashes and no direct model or GUI authority.

The equal experiment uses identical data, ordering, strategy fixture, risk policy, costs, calendars, external events and failure injections. Semantic fingerprints are compared before throughput, latency, memory, checkpoint size, recovery, licence and operational complexity.

A faster candidate that changes portfolio, order-lifecycle or accounting state relative to the common oracle is rejected. A candidate may be admitted for one role without becoming the universal engine.
