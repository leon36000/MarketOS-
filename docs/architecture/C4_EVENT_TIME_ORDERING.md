# C4 Event Time and Ordering

Each event records source time, venue time when available, receive wall time, receive monotonic time, persistence time, knowledge/availability time, source sequence and stable identity.

Economic time, knowledge time and elapsed time are distinct. UTC wall time represents chronology only with a quality envelope. Monotonic time measures durations and local deadlines.

Deterministic replay orders by availability time, source priority, source sequence, source event time, event-type priority and stable event ID. The ordering-policy version is included in the run fingerprint.

Clock quality records source, sync method, last sync, estimated/max error, offset, frequency error, leap state and hardware-timestamp capability. chrony is the baseline candidate; Linux PTP and hardware timestamping are conditional on measured value.

Excess uncertainty, stale synchronization, unresolved leap state or unbounded cross-node ordering causes quarantine or safe halt. Recorded timestamps are never rewritten merely to appear orderly.
