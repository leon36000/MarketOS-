# C4 Claude Code Execution Contract

## Objective

Design engine-neutral event, time, replay, lifecycle, FIX-session, durable-workflow and visual-tool boundaries that preserve determinism and safety.

## Scope

Canonical event envelope and ordering; clock-quality policy; engine bake-off; local and durable distribution; lifecycle/idempotency/reconciliation contracts; FIX recovery; Temporal boundary; API-before-Holo hierarchy.

## Out of scope

No engine, bus, external adapter or venue is selected. No live route, secret or certification is enabled.

## Future implementation map

```text
runtime/events/
runtime/time/
runtime/bus/
runtime/execution/
runtime/workflows/
runtime/tools/visual_bridge.py
tests/events/
tests/time/
tests/execution/
tests/tools/
benchmarks/C4/
```

## Test-first sequence

1. Create equal-time events and require a stable total order.
2. Move wall time backwards and require monotonic duration behavior.
3. Repeat a durable record and require unchanged final domain state.
4. Interrupt an external operation before acknowledgement and require idempotent recovery plus reconciliation.
5. Lose FIX sequence state and require resend/gap recovery before normal flow.
6. Expire an intent and require rejection.
7. Compare engine adapters on an identical replay fingerprint.
8. Change a visual layout and require safe abort on failed pre/postconditions.

## Verification

```bash
python -m unittest discover -s tests -v
python tools/validate_repository.py --root . --json
python tools/regenerate_derived.py --root . --check --json
```

C4-specific assertions and mutations run in CI against the machine-readable decisions and requirement closure.

## Exit gate

`C4_DESIGN_GATE_PASS` requires the contracts, five mapped requirements, primary-source evidence, adverse mutations and explicit engine/bus/adapter/live gates left open.

## Rollback

Remove the signed C4 delta, restore the verified C3 checkpoint, regenerate derived files and reproduce C1-C3 validations.
