# C13 — Broker Capability, Reconciliation and Accounting

Broker/account capabilities are effective-dated written facts: supported instruments, venues, order types, time-in-force, shorting, margin, options permissions, fractional trading, market-data rights and paper limitations. Unknown capability is false.

Orders carry proposal, risk-decision, intent, client-order and idempotency identities. Retries first reconcile uncertain outcomes. Duplicate acknowledgements/fills cannot double-count quantity, cash or fees.

Double-entry accounting records exact cash, securities, lots, tax basis, FX, financing, borrow, fees, dividends, splits, mergers and other entitlements. Corrections append reversing/adjusting entries; balances are never edited in place.

Internal orders, executions, positions, cash, fees and statements are reconciled with broker evidence. Divergence enters `RECONCILIATION_REQUIRED`, blocks new risk and preserves both views until resolved.
