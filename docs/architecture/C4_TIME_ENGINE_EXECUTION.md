# C4 — Time, Engine, Bus and Execution Architecture

Economic, knowledge and elapsed time are distinct. Events preserve source/venue, receive wall, receive monotonic, persistence and strategy-availability times. Replay ordering is versioned and deterministic. UTC wall time requires a clock-quality envelope; monotonic time measures durations.

chrony is the NTP baseline candidate. PTP and hardware timestamping are conditional on measured economic value. Excess uncertainty or stale synchronization quarantines data or invokes a safe halt.

MARKET-OS owns event, instrument, portfolio, risk and order contracts. NautilusTrader is the preferred event-driven candidate, LEAN the comparison candidate and a custom core a fallback only after a demonstrated gap. Semantic fingerprints precede performance.

In-process deterministic messaging, durable distribution and workflow orchestration are separate. Distributed delivery defaults to at-least-once; stable IDs, idempotency, durable acknowledgement and reconciliation remain mandatory.

The authority chain is proposal → risk decision → signed expiring intent → OMS transition → external adapter → acknowledgement/fill/reject → reconciliation. FIX versions and sequence state are counterparty-specific and durable. Kill switch, cancel-all and stale-data/time/risk halts are deterministic and model-independent.
