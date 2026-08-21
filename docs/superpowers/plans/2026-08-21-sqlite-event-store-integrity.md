# SQLite Event Store Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `SQLiteEventStore` physically append-only and fail-closed on every public read and externally affected write without turning ordinary appends into quadratic work.

**Architecture:** SQLite triggers enforce physical mutation vetoes. Robust row verifiers reconstruct canonical domain records and return structured chain reports. Initialization and reads verify both ledgers, while ordinary writes use verified count/head caches, `PRAGMA data_version`, connection change counts and indexed tails to avoid unnecessary full replay.

**Tech Stack:** Python 3.12 standard library, SQLite WAL, `unittest`, MarketOS canonical JSON/SHA-256 contracts.

**Spec:** `docs/superpowers/specs/2026-08-21-sqlite-event-store-integrity-design.md`

## Global Constraints

- `live_trading = HARD_LOCKED`.
- `profitability = UNPROVEN`.
- No production database or external dependency is selected.
- No stub, skipped test, weakened integrity check or silent repair is permitted.
- Existing event/evidence JSON and hash-chain formats remain compatible.
- A normal append after initialization must not replay the full history.

---

### Task 1: Establish adversarial RED evidence

**Files:**
- Modify: `tests/test_store.py`
- Create: `tests/test_store_integrity_concurrency.py`

**Interfaces:**
- Consumes: existing `SQLiteEventStore`, `EventEnvelope` and `ChainVerification` APIs.
- Produces: executable acceptance contract for triggers, read integrity, reopen integrity, concurrency and append complexity.

- [ ] **Step 1: Add direct mutation tests**

```python
with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY_EVENTS"):
    connection.execute("UPDATE events SET event_json = '{}' WHERE event_id = 'one'")
```

Repeat for event delete and both evidence operations.

- [ ] **Step 2: Add forced-corruption tests**

Drop one guard in a separate connection, mutate a row, commit, then prove that `read_all`, `read_evidence`, `count`, append and reopen raise the appropriate chain-integrity code.

- [ ] **Step 3: Add robust diagnostic tests**

Call `SQLiteEventStore.verify_event_rows(rows)` and `verify_evidence_rows(rows)` on malformed JSON and assert the report contains `EVENT_JSON_INVALID:1` or `EVIDENCE_JSON_INVALID:1` instead of raising a JSON parser exception.

- [ ] **Step 4: Add append-complexity instrumentation**

```python
class CountingStore(SQLiteEventStore):
    event_verifications = 0

    @classmethod
    def verify_event_rows(cls, rows):
        cls.event_verifications += 1
        return super().verify_event_rows(rows)
```

Assert one initialization verification and no additional verification after 100 ordinary event appends and 100 ordinary evidence appends.

- [ ] **Step 5: Execute the RED suite**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_store tests.test_store_integrity_concurrency -v
```

Expected before implementation: failures for missing triggers, missing structured verifiers and non-fail-closed reads. Record the exact commit, workflow run and job.

---

### Task 2: Install and authenticate SQLite append-only guards

**Files:**
- Modify: `src/marketos/store.py`

**Interfaces:**
- Produces: `_TRIGGER_CONTRACTS`, `_create_schema()` and `_verify_schema_guards()`.

- [ ] **Step 1: Add four triggers to schema creation**

```sql
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'APPEND_ONLY_EVENTS');
END;
```

Implement the corresponding event delete and evidence update/delete triggers.

- [ ] **Step 2: Verify the installed trigger contracts**

Query `sqlite_master`, normalize whitespace/case and require the correct table, operation and `RAISE(ABORT, ...)` message. Reject conditional guards so a `WHEN 0` trigger cannot satisfy the contract.

- [ ] **Step 3: Run direct-mutation and legacy-schema tests**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_store.StoreTests.test_event_rows_reject_direct_update_and_delete \
  tests.test_store.StoreTests.test_evidence_rows_reject_direct_update_and_delete \
  tests.test_store_integrity_concurrency.StoreIntegrityConcurrencyTests.test_existing_legacy_schema_receives_append_only_guards -v
```

Expected: PASS.

---

### Task 3: Implement canonical chain verifiers

**Files:**
- Modify: `src/marketos/store.py`

**Interfaces:**
- Produces:
  - `SQLiteEventStore.verify_event_rows(rows) -> ChainVerification`
  - `SQLiteEventStore.verify_evidence_rows(rows) -> ChainVerification`

- [ ] **Step 1: Split row verification by responsibility**

Implement `_verify_event_row` and `_verify_evidence_row` so each returns its ordered error tuple and computed chain head.

- [ ] **Step 2: Reconstruct domain records**

Decode canonical decimal wrappers, rebuild `EventEnvelope`, recompute the event/evidence item hash and compare exact canonical JSON bytes.

- [ ] **Step 3: Preserve diagnostics on malformed content**

Catch deterministic decode/domain failures, append a structured error code, continue structural chain evaluation and return `ok=False`.

- [ ] **Step 4: Run corruption diagnostics**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_store.StoreTests.test_chain_tamper_is_reported_without_json_decode_escape \
  tests.test_store_integrity_concurrency.StoreIntegrityConcurrencyTests.test_malformed_evidence_json_is_reported_not_raised -v
```

Expected: PASS.

---

### Task 4: Enforce fail-closed initialization and reads

**Files:**
- Modify: `src/marketos/store.py`

**Interfaces:**
- Produces: `_initialize_integrity_state()` and `_read_verified_snapshot()`.

- [ ] **Step 1: Verify under a stable initialization writer boundary**

Use `BEGIN IMMEDIATE`, load both tables, require both reports, verify all guards, capture the verified state and commit. Close the connection before propagating any constructor failure.

- [ ] **Step 2: Verify one stable snapshot for every public read**

`read_all`, `read_evidence` and `count` must consume the rows already verified in their read transaction. If either chain or any guard is invalid, roll back and return nothing.

- [ ] **Step 3: Run read/reopen adversarial tests**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_store.StoreTests.test_forced_event_tamper_blocks_read_count_append_and_reopen \
  tests.test_store.StoreTests.test_forced_evidence_tamper_blocks_read_append_and_reopen \
  tests.test_store_integrity_concurrency.StoreIntegrityConcurrencyTests.test_evidence_corruption_blocks_every_public_read_surface -v
```

Expected: PASS.

---

### Task 5: Add efficient stale-state detection for writes

**Files:**
- Modify: `src/marketos/store.py`

**Interfaces:**
- Produces: `_TableState`, `_tail_state`, `_write_integrity_states` and `_cache_committed_states`.

- [ ] **Step 1: Cache verified table heads**

Persist the verified count/head pair for events and evidence after initialization and successful commits.

- [ ] **Step 2: Detect external and local changes**

Compare current `PRAGMA data_version`, `Connection.total_changes` and both indexed tails against the verified cache under `BEGIN IMMEDIATE`.

- [ ] **Step 3: Reverify only when state changed**

If any witness differs, replay both complete chains before insert or idempotent return. Otherwise validate the four fixed-size trigger contracts and append directly.

- [ ] **Step 4: Advance state only after commit**

Use the inserted sequence/head to update the target table state. Never promote a rolled-back result.

- [ ] **Step 5: Run performance and concurrency tests**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_store.StoreTests.test_normal_appends_do_not_rescan_full_history \
  tests.test_store_integrity_concurrency.StoreIntegrityConcurrencyTests.test_valid_external_appends_refresh_cached_integrity_state -v
```

Expected: PASS.

---

### Task 6: Reconcile repository evidence and execute full verification

**Files:**
- Create: `docs/implementation/SQLITE_EVENT_STORE_INTEGRITY.md`
- Modify: `MANIFEST.json` through `tools/regenerate_derived.py`

**Interfaces:**
- Produces: exact repository evidence for independent review.

- [ ] **Step 1: Document guarantees and non-goals**

State physical triggers, fail-closed surfaces, concurrency witnesses, complexity boundary, error codes and the absence of an external tamper anchor.

- [ ] **Step 2: Regenerate derived artifacts**

```bash
python tools/regenerate_derived.py --root . --json
```

Expected: only intentional files enter `MANIFEST.json`.

- [ ] **Step 3: Run focused and complete verification**

```bash
PYTHONPATH=src python -m unittest tests.test_store tests.test_store_integrity_concurrency -v
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/verify_foundation.py --json
python tools/verify_proof_engine.py --root . --json
python tools/validate_repository.py --root . --json
python -m compileall -q src tools tests
git diff --check
```

Expected: all commands return zero.

- [ ] **Step 4: Verify Sonar and exact-head CI**

Require a passing Sonar quality gate, no new vulnerability, and successful repository workflows on the exact candidate SHA.

- [ ] **Step 5: Request independent exact-SHA review**

Create a blind-review packet that contains the exact base, head, tree, changed files, RED/GREEN receipts and required verdict schema. Do not merge or close issue #32 until an independent reviewer approves the unchanged exact head.
