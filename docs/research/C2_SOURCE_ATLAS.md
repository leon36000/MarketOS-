# C2 Source Atlas

No source is adopted by this design. Each product remains subject to schema, timing, rights, cost, sample and reconciliation gates.

## Identity and filings

- SEC EDGAR: US submissions and structured company facts.
- SEDAR+: Canadian public filings.
- GLEIF: legal-entity identifiers and ownership relationships.
- OpenFIGI: external-identifier mapping candidate.
- ISO MIC: venue and market-segment identifiers.
- ISO/ANNA ISIN and CFI: instrument identification and classification.
- DTCC: US reference and corporate-action workflows.
- TMX Datalinx: Canadian market, reference and corporate-action products.
- Databento: normalized point-in-time reference candidate.

## Market observations

- CTA and UTP consolidated US equities.
- Direct venue feeds for depth, auctions and status.
- OPRA for listed options.
- TMX feeds for Canadian venues.
- CIRO and FINRA regulatory publications.
- Account-provider interfaces for operational reconciliation, never universal truth.

## Macro and statistics

- FRED and ALFRED for US series and vintages.
- BLS, BEA, US Treasury and Federal Reserve publications.
- Bank of Canada Valet.
- Statistics Canada Web Data Service.

## Rights boundary

News and social products remain C9 adapters, but C2 defines their storage, deletion, embedding, training, derived-data and cloud-use permissions before ingestion.

## Evidence boundary

Published evidence on delisting bias supports retaining failed and delisted securities. Evidence that historical databases can change supports preserving every received version and content hash.
