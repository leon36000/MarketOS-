# C2 — Security Master Contract

## Identity principle

A ticker is a human-facing attribute of a listing at a venue during a validity interval. It is never the primary key of an issuer, instrument, share class or listing.

```text
LegalEntity
  -> Issuer
      -> Instrument
          -> ShareClass
              -> Listing <-> Venue
```

Each object receives an immutable MARKET-OS UUID. External identifiers are assignments with source, scope, validity, knowledge time and confidence.

## Core entities

### LegalEntity

Represents a legally constituted organization. It may possess an LEI and parent/child relationships but is not assumed to equal an issuer.

### Issuer

Entity responsible for an instrument. Corporate restructurings can terminate, merge or replace an issuer without silently rewriting historical instruments.

### Instrument

The economically fungible security or contract. Required attributes include type, currency/par value where applicable, CFI/FISN candidates, issue/maturity lifecycle and issuer relationship.

### ShareClass

Separates economically distinct classes issued by the same entity. Voting, dividend, conversion and restriction attributes are versioned.

### Listing

Tradable appearance of an instrument/share class on a venue. It carries venue, local symbol, currency, status, listing/delisting dates, lot, tick regime and trading calendar references.

### Venue

Identified primarily by versioned ISO 10383 MIC assignments. Operating MIC and segment MIC are stored separately.

## Identifier assignments

```yaml
assignment_id:
marketos_object_id:
identifier_type:
identifier_value:
scope: entity|issuer|instrument|share_class|listing|venue
source_id:
valid_from:
valid_to:
first_seen_at:
available_to_strategy_at:
revision_time:
status: active|corrected|retracted|disputed
confidence:
```

Supported mappings include FIGI, composite/share-class FIGI, ISIN, CUSIP, SEDOL, CIK, LEI, CFI, FISN, MIC, local symbols and vendor symbols. Absence or conflict is represented explicitly.

## Continuity rules

- Name or symbol change normally preserves listing identity while producing new attribute versions.
- Currency-specific or venue-specific appearances are distinct listings.
- Cross-listings link to a common instrument/share class when fungibility is proven.
- Spin-offs create new instruments/listings; the parent retains its own history.
- Merger identity depends on legal/economic continuity and source evidence; it is never inferred from a ticker.
- A delisted listing remains queryable. A later relisting can be linked or separated according to documented continuity.
- Bankruptcy and liquidation statuses do not delete the instrument.

## Universe construction

Current and historical universe queries are separate APIs.

A historical universe requires:

- listing active at the economic cutoff;
- status and identifier versions known by the knowledge cutoff;
- venue/calendar availability;
- no exclusion based on future survival, future index membership or present-day vendor availability.

Every membership record stores inclusion/exclusion reason, effective time, knowledge time and source.

## Survivorship and delisting

Inactive, acquired, bankrupt, delisted and renamed securities remain in the historical namespace. Missing delisting returns are a quality defect, not permission to drop the observation. Any fallback estimate must be strategy-independent, versioned and reported separately from observed returns.

## Point-in-time query

```text
valid_from <= economic_cutoff < valid_to
AND available_to_strategy_at <= knowledge_cutoff
```

Corrections arriving later are invisible before their knowledge time. Current cleaned data cannot be substituted for a historical snapshot.

## Quality gates

- duplicate internal identity;
- simultaneous conflicting active identifier assignment;
- symbol without venue and interval;
- unknown MIC or calendar;
- missing listing status history;
- deletion of inactive security;
- unexplained identity merge/split;
- future membership leakage;
- source history replaced without a retained version.
