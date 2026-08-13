# C2 — Claude Code Execution Contract

## Objective

Build the Security Master, corporate-action, source-admission, rights/TCO and data-procurement foundations needed for survivorship-free point-in-time research.

## Scope

- internal entity and listing identity model;
- bitemporal identifier assignments and trading-status history;
- corporate-action lifecycle, corrections, cancellations and adjustment factors;
- official and licensed source atlas for initial US/Canada coverage;
- rights and TCO policy objects enforced fail-closed;
- L0/L1/L2/L3 procurement and value gates;
- vendor RFQ and cross-source reconciliation.

## Out of Scope

- purchasing data;
- adopting a vendor;
- claiming real data quality;
- implementing the final storage engine;
- enabling live trading.

## Required Files

```text
runtime/reference/contracts.py
runtime/reference/security_master.py
runtime/reference/corporate_actions.py
runtime/reference/identifier_history.py
runtime/data/rights_policy.py
runtime/data/source_admission.py
runtime/data/tco.py
runtime/data/reconciliation.py
tests/reference/
tests/data_rights/
benchmarks/C2/
phases/C2/
```

## Interfaces

`LegalEntity`, `Issuer`, `Instrument`, `ShareClass`, `Listing`, `Venue`, `IdentifierAssignment`, `CorporateActionEvent`, `TradingStatusEvent`, `RightsPolicy`, `TCOScenario`, `SourceQualification` and `ReconciliationDecision` are immutable versioned contracts.

## TDD sequence

1. RED: prove symbol reuse and cross-listing collisions break a ticker-keyed model.
2. GREEN: implement stable internal IDs and versioned external mappings.
3. RED: expose a future corporate-action correction to an earlier backtest and require failure.
4. GREEN: implement dual-time event versions, cancellations and retractions.
5. RED: remove delisted securities and demonstrate the universe changes incorrectly.
6. GREEN: preserve inactive listings, delisting returns and historical memberships.
7. RED: leave any right unknown and require denial.
8. GREEN: implement field-level rights decisions and audit receipts.
9. RED: omit storage, egress, compliance or exit cost and require incomplete TCO.
10. GREEN: implement complete scenario TCO and uncertainty ranges.
11. RED: present conflicting sources without quarantine.
12. GREEN: implement precedence, contradiction and reconciliation records.

## Verification commands

```bash
python -m unittest discover -s tests -v
python tools/validate_c2_design.py --root . --json
python tools/validate_repository.py --root . --json
python tools/regenerate_derived.py --root . --check --json
```

## Failure injection

- reused ticker on the same venue;
- cross-listed share class with different currencies;
- merger creating a new instrument;
- spin-off incorrectly inheriting identity;
- delisting followed by relisting;
- correction received after the simulated decision time;
- vendor silently rewrites history;
- missing delisting return;
- unknown embedding or cloud right;
- licence expiry and mandatory deletion;
- source disagreement and schema drift;
- L3 sample with a different depth than its message file.

## Exit Gate

`C2_DESIGN_GATE_PASS` requires machine-readable identity, event, rights, TCO, source and procurement contracts; six mapped requirements; official-source evidence; negative tests; and an explicit list of provider and real-data gates left open.

## Rollback

Remove only files listed in the signed C2 delta, restore the C1 Current State and phase index, regenerate derived files and prove repository validation returns to the C1 checkpoint.
