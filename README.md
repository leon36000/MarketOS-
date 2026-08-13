# MARKET-OS

Private autonomous market research, simulation, portfolio-risk and execution system.

## Current state

- This repository completes the **design plan** before Claude Code builds the final software.
- Planning roadmap: `C1` through `C16`.
- Active branch: `plan/c1-foundation`.
- Neon memory schema: `marketos_memory` in project `frosty-boat-02108163`.
- `live_trading_state = HARD_LOCKED`.
- `profitability = UNPROVEN`.

## C1

C1 defines deployment profiles, complete-application evaluation, secrets, observability, alerts,
notifications and runbooks. It does not implement financial trading.

```bash
python tools/materialize_c1_bundle.py . --replace
python -m pip install -e ".[dev]"
python -m pytest -q
python tools/validate_c1.py .
```

No phase is complete without traceable requirements, evidence, tests, falsification attempts,
rollback and a gate report.
