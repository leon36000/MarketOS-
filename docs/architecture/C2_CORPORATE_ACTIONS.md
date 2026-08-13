# C2 — Corporate Actions Contract

## Truth model

Raw price observations and corporate-action events are separate authorities. MARKET-OS does not overwrite raw prices with an adjusted series. Adjustment factors are reproducible, method-versioned derived data.

## Event model

```yaml
event_id:
event_family:
issuer_id:
instrument_id:
listing_ids: []
source_id:
source_event_id:
version:
status: announced|confirmed|corrected|cancelled|effective|expired
announcement_date:
ex_date:
record_date:
effective_date:
payable_date:
expiration_date:
terms:
valid_from:
valid_to:
first_seen_at:
available_to_strategy_at:
revision_time:
raw_payload_sha256:
previous_version_id:
```

Event families include cash/stock dividends, splits, reverse splits, mergers, acquisitions, spin-offs, rights issues, tender offers, redemptions, name/symbol changes, listings, delistings, bankruptcy and reorganizations.

## Lifecycle

1. Capture every source version and raw payload.
2. Normalize without destroying source-specific fields.
3. Link related events and affected listings.
4. Reconcile conflicts under source precedence and human-review policy.
5. Derive entitlements and adjustment factors using a named method version.
6. Publish a point-in-time view only after temporal and rights checks.

A correction or cancellation appends a new version. The superseded record remains visible for historical queries before the new knowledge time.

## Adjustment policy

Derived outputs are separated by purpose:

- split-adjusted price/volume;
- total-return series;
- cash-flow entitlement ledger;
- shares-outstanding adjustment;
- option-contract adjustment inputs;
- tax/accounting treatment.

Each output stores the event set, formula, currency/FX source, rounding, effective convention, build time, code version and result hash. Vendors can disagree; MARKET-OS compares factors rather than silently picking one.

## Identity effects

- Symbol/name changes do not create economic returns.
- Splits preserve instrument identity and alter units.
- Spin-offs create new instrument identities plus an entitlement from the parent.
- Mergers/acquisitions define predecessor/successor relationships and consideration components.
- Delisting marks listing status; it does not delete history.
- Relisting continuity requires evidence, not symbol equality.

## Historical replay

At a simulated decision time, only event versions with `available_to_strategy_at` at or before the cutoff are usable. An event's effective date does not imply it was known on that date. Announced events can be model inputs only when captured and permitted by the strategy.

## Conflict handling

Conflicting amount, ratio, date, currency or status creates `DISPUTED`. T0/T1 evidence receives higher default authority, but no precedence rule may erase the minority record. Material unresolved conflicts quarantine derived adjusted data.

## Testing cases

- split announced, corrected and later cancelled;
- dividend amount revised after ex-date;
- spin-off with when-issued listing;
- cash/stock mixed merger;
- symbol change overlapping two vendors;
- delisting with missing final trade or return;
- relisting after dormancy;
- vendor historical record changes between downloads;
- event effective before the source was first seen.
