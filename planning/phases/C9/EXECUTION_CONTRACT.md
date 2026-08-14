# C9 — Claude Code Execution Contract

## Objective

Implement point-in-time macro vintages, probabilistic regimes, real-time event capture, corroboration and rights-aware alternative-data features.

## Required surfaces

```text
runtime/macro/
runtime/regimes/
runtime/events/social/
runtime/events/corroboration.py
runtime/alternative_data/
tests/macro/
tests/events/
tests/alternative_data/
benchmarks/C9/
```

## Test-first sequence

1. Current revised macro history must be invisible to an earlier context.
2. Scheduled release and actual first availability must remain distinct.
3. Duplicate, edit, delete, reconnect and sequence-reset events must replay deterministically.
4. One unverified item cannot escalate authority or increase exposure.
5. The fast path cannot bypass portfolio/risk controls.
6. Corroboration must distinguish shared upstream origin from independent sources.
7. Simplified unauthenticated streams cannot become authoritative without verification.
8. Expired retention, embedding, training or cloud permissions must veto use.
9. Regime uncertainty must permit abstention.

## Qualification boundary

No macro, news or social product and no regime method is selected. Real continuity, rights, latency, manipulation resistance and out-of-sample value remain separate gates.

## Rollback

Disable adapters, revoke source credentials, preserve raw/event evidence under permitted retention, invalidate derived contexts and restore the C8 checkpoint.
