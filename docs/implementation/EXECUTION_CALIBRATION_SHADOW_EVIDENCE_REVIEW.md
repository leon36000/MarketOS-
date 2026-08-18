# Independent Review — Execution Calibration and Shadow Evidence

## Review scope

This review covers the provider-neutral execution-evidence, calibration, reality-gap, shadow-evidence and conservative-capacity slice on `codex/execution-calibration-shadow-evidence`. Review authority is limited to research controls and software invariants; it does not attest empirical broker calibration, live readiness, strategy edge or profitability.

## Evidence observed

### TDD RED

GitHub Actions run `32188111045`, job `95876305565`, executed the new acceptance contract before the verifier existed. The single acceptance test failed exactly with `ModuleNotFoundError: No module named 'tools.verify_execution_calibration'`, and the one-shot harness recorded the expected RED. The harness was removed after that proof.

### Independent verifier

`tools/verify_execution_calibration.py` exercises ten cross-module controls rather than trusting module-local flags. The acceptance test requires exactly ten passes and verifies that live trading, profitability, simulator calibration, broker-feed qualification, capacity qualification, capital authorization, strategy-edge proof and production-backend selection cannot be promoted by this slice.

### Pre-existing test defect discovered during GREEN

The first focused GREEN attempt exposed a pre-existing inconsistency in `test_versions_are_append_only_and_identity_stable`: the duplicate fixture changed `opportunity_fill_ratio` without recomputing `fill_ratio_gap`, so the production invariant correctly rejected the object before the intended duplicate-conflict assertion.

The repair did **not** weaken production validation. Commit `eef78f8efce21fbd826913dcaf1e52601a811cd5` changes the fixture to keep `fill_ratio_gap = -0.30` when opportunity fill is changed to `0.50`, preserving an internally valid but ledger-conflicting record. The one-shot repair workflow executed the shadow-evidence test module and the independent verifier before committing, then removed itself.

## Ten independent acceptance checks

1. `broker_observed_truth_firewall`
2. `append_only_execution_evidence`
3. `explicit_assumptions_and_contiguous_fidelity`
4. `contextual_prediction_surface_is_strict`
5. `reality_gap_families_cannot_be_masked`
6. `independent_review_only_challenger_gate`
7. `shadow_counterfactual_truth_firewall`
8. `append_only_shadow_evidence`
9. `conservative_research_capacity_bound`
10. `fail_closed_capacity_and_global_authority`

## Historical-memory correction

Earlier persistent-memory records labeled `CANDIDATE_PR20` through `CANDIDATE_PR24` were not accepted as remote GitHub proof: before this slice was materialized, direct GitHub lookups for PRs #20–#24 and the five recorded candidate branch names returned not found. Those records may describe local or intended work, but they were not reproducibly bound to remote PR identities or exact GitHub SHAs.

The current draft PR #20 is a new, real GitHub object for `codex/execution-calibration-shadow-evidence`, stacked on PR #19. Its evidence must be tied only to its actual head SHA and workflow runs.

## Residual risks and non-claims

- No observed broker feed is qualified.
- No empirical production fill model is calibrated.
- No broker or production execution backend is selected.
- Capacity remains a research-only upper bound based on supplied distributions and constraints.
- Shadow evidence remains counterfactual even when linked to separately verified broker evidence.
- PC1/PC2 local runtime state was not independently observed in this review because MCP_TO_PC was not exposed in the active connector registry.
- PR14 architectural work remains divergent from the executable PR15→PR20 stack and requires explicit reconciliation.
- `profitability = UNPROVEN` and `live_trading = HARD_LOCKED` remain unchanged.

## Promotion rule

No claim from this slice may be promoted beyond its current research authority without fresh exact-head CI evidence and, for empirical execution claims, independently verified broker-observed data with provenance.