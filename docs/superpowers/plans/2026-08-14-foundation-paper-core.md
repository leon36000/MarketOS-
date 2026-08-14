# MARKET-OS Foundation and Paper-Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working, deterministic, non-live MARKET-OS foundation covering canonical evidence, exact finance values, event ordering, append-only accounting, deterministic risk decisions, paper execution, replay, persistence and an operator CLI.

**Architecture:** A dependency-light Python 3.12 package under `src/marketos` owns all financial and evidence contracts. Immutable domain objects feed a hash-chained event store, an exact double-entry ledger, a position book and a deterministic Risk Kernel. A paper broker and replay engine form a complete vertical slice; live execution is structurally unavailable.

**Tech Stack:** Python 3.12 standard library, `dataclasses`, `decimal`, `sqlite3`, `hashlib`, `argparse`, `unittest`, `tomllib`/JSON configuration.

## Global Constraints

- `live_trading = HARD_LOCKED` in code, configuration and CLI.
- `profitability = UNPROVEN`; no performance or edge claim is emitted.
- No binary floating-point values in authoritative cash, fees, quantities, prices or limits.
- Every mutation is append-only, versioned or represented by a compensating event.
- Distributed or repeated inputs must be idempotent by stable IDs.
- Wall-clock time is not used for elapsed durations; event and knowledge times are separate.
- No external package or network access is required for the foundation test suite.
- Tests must be written and observed failing before each production slice.

---

### Task 1: Package and canonical evidence primitives

**Files:**
- Create: `pyproject.toml`
- Create: `src/marketos/__init__.py`
- Create: `src/marketos/errors.py`
- Create: `src/marketos/canonical.py`
- Test: `tests/test_canonical.py`

**Interfaces:**
- Produces: `canonical_json(value) -> str`, `canonical_sha256(value) -> str`, `DomainError`, `InvariantViolation`, `DuplicateConflict`.

- [ ] Write failing tests for stable map ordering, exact `Decimal` encoding, dataclass/enum support and non-finite rejection.
- [ ] Run `python -m unittest tests.test_canonical -v` and confirm failure because `marketos.canonical` does not exist.
- [ ] Implement canonical conversion and hashing with no float acceptance.
- [ ] Run the focused test and then the full suite.
- [ ] Commit `feat: add canonical evidence primitives`.

### Task 2: Exact financial values

**Files:**
- Create: `src/marketos/money.py`
- Test: `tests/test_money.py`

**Interfaces:**
- Produces: `Money`, `Quantity`, `Price`, `CurrencySpec`, `RoundingPolicy`.
- `Money.from_decimal(currency: str, value: str | Decimal, rounding=...) -> Money`.
- `Price.notional(quantity: Quantity) -> Money`.

- [ ] Write failing tests for float rejection, currency mismatch, exact arithmetic, tick validation, explicit rounding and negative/zero quantity rules.
- [ ] Run focused tests and verify the intended missing-module failure.
- [ ] Implement immutable scaled-money, decimal quantity and tick-aware price types.
- [ ] Run focused and full tests.
- [ ] Commit `feat: add exact financial value types`.

### Task 3: Event time and deterministic total ordering

**Files:**
- Create: `src/marketos/time.py`
- Create: `src/marketos/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces: `ClockQuality`, `EventTime`, `EventEnvelope`, `EventKind`, `sort_events(events)`.
- Canonical order: availability time, source priority, source sequence, event time, kind priority, stable event ID.

- [ ] Write failing tests for total-order ties, knowledge-time look-ahead rejection, UTC/monotonic validation and immutable payloads.
- [ ] Verify RED.
- [ ] Implement time quality and event contracts.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add deterministic event contracts`.

### Task 4: Hash-chained SQLite event and evidence store

**Files:**
- Create: `src/marketos/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `SQLiteEventStore(path)`, `append(envelope)`, `read_all()`, `verify_chain()`, `append_evidence(kind, payload)`.
- Duplicate event IDs with identical bytes are idempotent; conflicting duplicates raise `DuplicateConflict`.

- [ ] Write failing tests for durable append, duplicate idempotency, conflicting duplicate rejection, chain tamper detection and transaction rollback.
- [ ] Verify RED.
- [ ] Implement SQLite schema, WAL mode, immutable insert and chain verification.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add hash-chained event store`.

### Task 5: Exact double-entry ledger and position book

**Files:**
- Create: `src/marketos/ledger.py`
- Create: `src/marketos/portfolio.py`
- Test: `tests/test_ledger.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Produces: `Posting`, `JournalEntry`, `Ledger`, `PositionLot`, `PositionBook`, `PortfolioSnapshot`.
- Journal entries balance independently per currency; corrections use reversal entries.

- [ ] Write failing tests for unbalanced rejection, duplicate idempotency, immutable corrections, funding, buy/sell average cost, fee handling and realized PnL.
- [ ] Verify RED.
- [ ] Implement ledger and position application.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add exact ledger and portfolio books`.

### Task 6: Signed order intents and deterministic Risk Kernel

**Files:**
- Create: `src/marketos/orders.py`
- Create: `src/marketos/risk.py`
- Test: `tests/test_risk.py`

**Interfaces:**
- Produces: `OrderIntent`, `OrderSide`, `OrderType`, `TimeInForce`, `RiskLimits`, `RiskContext`, `RiskDecision`, `RiskAction`, `RiskKernel.evaluate(...)`.
- Live mode is absent from the public constructor; policy always reports hard-locked live state.

- [ ] Write failing tests for stale data, clock uncertainty, unreconciled books, unsupported instrument, expired intent, cash/position/exposure/order-size limits and valid paper approval.
- [ ] Verify RED.
- [ ] Implement deterministic fail-closed evaluation and decision hashing.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add deterministic risk kernel`.

### Task 7: Paper broker, fills and exact accounting integration

**Files:**
- Create: `src/marketos/paper.py`
- Test: `tests/test_paper.py`

**Interfaces:**
- Produces: `MarketSnapshot`, `Fill`, `PaperBroker`, `ExecutionReport`.
- Supports market and marketable limit orders, bounded partial fills, deterministic slippage/fees, duplicate-safe execution and no shorting.

- [ ] Write failing tests for buy/sell accounting, limit rejection, partial fill, duplicate intent idempotency, insufficient cash/position and exact realized PnL.
- [ ] Verify RED.
- [ ] Implement paper execution integrated with Risk Kernel, Ledger and PositionBook.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add deterministic paper broker`.

### Task 8: Deterministic replay and checkpoint/resume

**Files:**
- Create: `src/marketos/replay.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces: `ReplayEngine`, `ReplayConfig`, `ReplayCheckpoint`, `ReplayResult`.
- Consumes `MARKET_SNAPSHOT` and `ORDER_INTENT` events and emits risk/execution evidence.

- [ ] Write failing tests for input-order independence, identical fingerprints, checkpoint/resume identity, max-event stop and look-ahead rejection.
- [ ] Verify RED.
- [ ] Implement deterministic state machine and JSON checkpoint serialization.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add deterministic paper replay`.

### Task 9: Runtime configuration and CLI

**Files:**
- Create: `src/marketos/config.py`
- Create: `src/marketos/cli.py`
- Create: `src/marketos/__main__.py`
- Create: `config/paper-risk.json`
- Create: `examples/paper_scenario.jsonl`
- Test: `tests/test_cli.py`

**Interfaces:**
- `python -m marketos validate-config --risk config/paper-risk.json`.
- `python -m marketos replay --input examples/paper_scenario.jsonl --risk ... --db ...`.
- CLI prints machine-readable JSON and always reports live hard locked.

- [ ] Write failing CLI tests for config validation, scenario replay, invalid float input and forbidden live flag.
- [ ] Verify RED.
- [ ] Implement strict config loader and CLI.
- [ ] Verify GREEN and full suite.
- [ ] Commit `feat: add paper-core CLI`.

### Task 10: Documentation, CI and integrated verification

**Files:**
- Create: `docs/implementation/FOUNDATION_PAPER_CORE.md`
- Create: `.github/workflows/implementation-foundation.yml`
- Create: `tools/verify_foundation.py`
- Test: `tests/test_foundation_acceptance.py`

**Interfaces:**
- `python tools/verify_foundation.py --json` produces an acceptance report.

- [ ] Write failing acceptance test requiring package import, exact money, replay fingerprint, tamper detection, risk vetoes and CLI smoke.
- [ ] Verify RED.
- [ ] Implement verifier, documentation and CI workflow.
- [ ] Run `python -m unittest discover -s tests -v`, `python -m compileall -q src tools tests`, CLI replay twice and compare fingerprints.
- [ ] Review diff for secrets, live routes, floats and unrelated files.
- [ ] Commit `feat: deliver MARKET-OS foundation paper-core vertical slice`.
