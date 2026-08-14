# MARKET-OS Foundation and Paper-Core

This implementation slice is executable software, not a profitability or live-readiness claim.

## Delivered runtime

- canonical JSON and SHA-256 evidence primitives that reject binary floats;
- exact currency minor units, decimal quantities and tick-aligned prices;
- separate event, availability, wall and monotonic times;
- deterministic total event ordering;
- SQLite append-only event/evidence chains with idempotency and tamper detection;
- exact double-entry journal, reversals and average-cost position book;
- immutable paper order intents and a deterministic fail-closed Risk Kernel;
- deterministic paper fills, fees, partial fills and reconciliation-safe duplicate handling;
- replay with stable fingerprints and checkpoint/resume equivalence;
- strict JSON configuration and a machine-readable CLI.

## Run

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/verify_foundation.py --json
PYTHONPATH=src python -m marketos validate-config --risk config/paper-risk.json
PYTHONPATH=src python -m marketos replay \
  --input examples/paper_scenario.jsonl \
  --risk config/paper-risk.json \
  --initial-cash 1000.00 \
  --db /tmp/marketos-paper.sqlite3
```

## Authority boundary

```yaml
live_trading: HARD_LOCKED
profitability: UNPROVEN
broker_connectivity: NOT_IMPLEMENTED
external_market_data: NOT_IMPLEMENTED
production_risk_qualification: NOT_RUN
```

The public `ExecutionMode` contains only `SHADOW` and `PAPER`. There is no live broker adapter or live command. The paper fill model is deterministic and deliberately conservative, but it is not calibrated against real fills.

## Next implementation nodes

1. Persist exact journals and portfolio snapshots in the authoritative store.
2. Add Security Master and corporate-action identities.
3. Add data-source capture and point-in-time dataset publication.
4. Add strategy/plugin interfaces and experiment ledger.
5. Add Node Pack/Compute Fabric probes and the CPU numerical oracle suite.
