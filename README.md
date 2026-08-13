# MARKET-OS

Private autonomous market research, simulation, portfolio-risk and execution system.

## Current state

- Repository initialized for **plan completion**, not live trading.
- Planning closure roadmap: `C1` through `C16`.
- Active slice: `C1 — deployment, containers and operability`.
- External memory control plane: Neon Postgres candidate plus verified file canon.
- `live_trading_state = HARD_LOCKED`
- `profitability = UNPROVEN`

## Verify

```bash
python -m unittest discover -s tests -v
python tools/validate_repository.py --root . --json
```

## First principle

No phase is complete without traceable requirements, evidence, tests, falsification attempts, rollback and a gate report.
