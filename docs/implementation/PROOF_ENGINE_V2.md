# Proof Engine v2

## Scope

Proof Engine v2 validates claims against exact repository evidence. It binds
the current reconciliation matrix, current authority state, canonical
requirement oracle and repository manifest to a versioned fail-closed policy.
The separate `PROOF_BINDING.json` ledger pins the three local authority
artifacts and every PR14–PR20 receipt to exact hashes and SHAs; it records
evidence identity without granting promotion authority.
It does not query GitHub at runtime and it does not authorize trading,
capital, profitability or production backends.

The 108-to-119 boundary is intentionally safe but incomplete. The repository
oracle has 108 rows, `CURRENT_STATE.json` records 119 observed memory rows,
and the local memory snapshot exposes 111 rows without a row-level export.
`verify_requirements_reconciliation.py` records both findings and keeps
promotion disabled; it does not invent the missing eight rows or silently
promote the memory set.

## Thirteen checks

The verifier requires all thirteen checks to pass:

1. policy flags are versioned and complete;
2. every source authority path resolves inside the repository;
3. architecture reconciliation is independently valid;
4. current state matches the reconciliation candidate and locks;
5. the repository oracle contains 108 canonical requirements;
6. the memory observation set remains a separate 119-row superset;
7. zero broad implementation nodes are falsely promoted complete;
8. live trading remains `HARD_LOCKED`;
9. profitability remains `UNPROVEN`;
10. stale or failed evidence cannot be promoted;
11. the proof ledger is append-only by policy;
12. the pinned PR14 and PR20 SHA bindings match the reconciliation evidence;
13. the complete PR14–PR20 proof-binding ledger matches artifact hashes, exact
    SHAs, receipts and current state.

Any missing path, changed authority value, stale reconciliation or weakened
lock produces a non-zero result. A report with fewer than thirteen passed checks
is never accepted. A passing binding ledger still describes partial evidence;
it does not make C13–C15 complete or reconcile the 119 observed memory rows
with the 108 canonical requirements.

## Explicit non-goals

- no remote CI status is inferred from a branch name;
- no unresolved memory reference becomes canonical evidence;
- no partial execution slice becomes a completed architecture node;
- no Proof Engine result unlocks a live route or proves a strategy edge.

## Verification

```bash
PYTHONPATH=src python -m unittest tests.test_proof_engine tests.test_proof_engine_acceptance -v
python tools/verify_proof_binding.py --json
python tools/verify_requirements_reconciliation.py --json
python tools/verify_proof_engine.py --json
```
