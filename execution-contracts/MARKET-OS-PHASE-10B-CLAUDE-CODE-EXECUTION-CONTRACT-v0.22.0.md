# Phase 10B — Claude Code Execution Contract : CPU Golden Oracle

> **For Claude Code:** execute task-by-task with TDD. No task may alter live, provider, storage or strategy gates.

**Goal:** construire un noyau numérique CPU de référence, déterministe et auditable pour tous les calculs financiers critiques.

**Architecture:** les quantités monétaires et de position utilisent des types exacts; les statistiques et risques utilisent des chemins FP64 avec diagnostics; tout futur GPU/NPU/FPGA est comparé à ces oracles et automatiquement mis en quarantaine lors d’une divergence.

**Tech stack:** Python 3.13 standard library, NumPy exact wheel lorsque disponible, `decimal`, `fractions`, `pytest`, Hypothesis si wheel qualifié, JSON canonicalisé.

## Global Constraints

- `HARD_LOCKED` demeure inchangé.
- Aucune dépendance réseau pendant les tests qualifiants.
- Aucun résultat NaN/Inf dans un artefact canonique.
- Toutes les réductions parallèles ont un ordre stable.
- Les seuils d’erreur sont définis par workload et testés contre des contre-exemples.
- Les fichiers restent focalisés; aucune classe monolithique.

## File map

```text
runtime/math/domain.py
runtime/math/fixed_point.py
runtime/math/stable_reductions.py
runtime/math/covariance.py
runtime/math/tail_risk.py
runtime/math/monte_carlo.py
runtime/math/error_budget.py
runtime/math/fallback.py
runtime/math/service.py
tests/math/*.py
benchmarks/10B/run_cpu_golden_oracle.py
phases/10B/results/*.json
```

## Interfaces obligatoires

```python
@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str

@dataclass(frozen=True)
class ScaledPrice:
    ticks: int
    tick_size_minor_units: int
    currency: str

@dataclass(frozen=True)
class ErrorBudget:
    absolute: float
    relative: float
    ulp: int
    distribution_distance: float

@dataclass(frozen=True)
class KernelEvidence:
    workload_id: str
    implementation_id: str
    input_sha256: str
    output_sha256: str
    diagnostics: dict[str, object]

def expected_shortfall(losses: Sequence[float], alpha: float) -> float: ...
def covariance_report(matrix: NDArray[np.float64]) -> CovarianceReport: ...
def deterministic_monte_carlo(spec: MonteCarloSpec) -> MonteCarloResult: ...
def compare_to_oracle(reference: ArrayLike, candidate: ArrayLike, budget: ErrorBudget) -> DifferentialReport: ...
```

## Task 1 — Exact monetary domain

- [ ] Write tests for currency mismatch, tick conversion, overflow boundary, fee accumulation and exact round-trip serialization.
- [ ] Run `python -m pytest tests/math/test_fixed_point.py -q`; expected RED.
- [ ] Implement immutable exact types using integers and explicit currency/tick metadata.
- [ ] Run the same command; expected all PASS.

## Task 2 — Stable reductions

- [ ] Test catastrophic cancellation vectors against `math.fsum`.
- [ ] Test mergeable Welford/Chan moments across 1, 2, 4 and 8 partitions.
- [ ] Implement Kahan/Neumaier/pairwise and mergeable moments.
- [ ] Prove order policy in the evidence report; no unordered hash-map reduction.

## Task 3 — Covariance and conditioning

- [ ] Test symmetric output, PSD diagnostics, singular matrix, high condition number and repaired matrix.
- [ ] Implement sample covariance reference, eigenvalue diagnostics, shrinkage hook and explicit repair report.
- [ ] Reject silent repair; expose original and repaired spectra.

## Task 4 — VaR, Expected Shortfall and stress

- [ ] Test exact small distributions, interpolation boundaries, repeated values, empty input and invalid alpha.
- [ ] Implement deterministic quantiles, historical VaR, ES and weighted stress aggregation.
- [ ] Assert ES is at least VaR for the MARKET-OS loss convention.

## Task 5 — Deterministic Monte-Carlo

- [ ] Test same fingerprint across 1/2/4 workers and checkpoint/resume.
- [ ] Test that changing seed, algorithm version or spec changes run identity.
- [ ] Implement fixed chunk IDs, per-chunk RNG streams and stable reduction order.
- [ ] Never use global process RNG state.

## Task 6 — Error budgets and fallback

- [ ] Test absolute, relative, ULP and distribution thresholds independently.
- [ ] Test a candidate that passes averages but changes a portfolio decision; it must fail.
- [ ] Implement `PASS`, `QUARANTINE`, `FALLBACK_CPU` and evidence records.

## Task 7 — Kernel service

- [ ] Test typed request validation, input hashing, implementation version and evidence serialization.
- [ ] Ensure LLM-originated parameters cannot bypass bounds.
- [ ] Implement a local in-process API first; do not introduce MCP or network transport in 10B.

## Task 8 — Qualification harness

- [ ] Execute exact-money, cancellation, singular covariance, heavy-tail, Monte-Carlo and decision-boundary fixtures.
- [ ] Label performance as target-unqualified.
- [ ] Produce hashes, versions, diagnostics, counts and no non-finite JSON.

## Task 9 — Adversarial review and gate

- [ ] Mutate currency, seed, alpha, reduction order, matrix conditioning, error tolerance and implementation ID.
- [ ] Require each mutation to hit its intended semantic control.
- [ ] Gate only `CPU_GOLDEN_ORACLE_LOCAL_PASS`; leave GPU, target hardware, strategy, profit and live open.

## Rollback

Delete only files declared by the 10B delta, restore the previous Current State and rerun the release validator. No database migration or live state exists in this phase.

## Handoff

The next phase receives exact function signatures, golden fixtures and `ErrorBudget` objects. GPU/NPU/FPGA implementations are forbidden from defining their own truth thresholds.
