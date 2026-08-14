#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one patch site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "src/marketos/validation.py"
replace_once(
    path,
    '''from dataclasses import dataclass
import re
from typing import Iterable

from .canonical import canonical_sha256
from .errors import InvariantViolation
''',
    '''from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Iterable

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .experiments import TrialRecord
''',
)

with Path(path).open("a", encoding="utf-8") as handle:
    handle.write(
        r'''


class BaselineKind(str, Enum):
    NO_TRADE = "NO_TRADE"
    BUY_AND_HOLD = "BUY_AND_HOLD"
    SIMPLE_RULE = "SIMPLE_RULE"


class FidelityStage(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    BAR_REPLAY = "BAR_REPLAY"
    EVENT_REPLAY = "EVENT_REPLAY"
    SHADOW = "SHADOW"


_FIDELITY_ORDER = (
    FidelityStage.SYNTHETIC,
    FidelityStage.BAR_REPLAY,
    FidelityStage.EVENT_REPLAY,
    FidelityStage.SHADOW,
)


def _decimal(value: Decimal, code: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(code)
    return value


def _unique_text_tuple(
    values: Iterable[str],
    *,
    empty_code: str,
    duplicate_code: str,
) -> tuple[str, ...]:
    materialized = tuple(_text(value, empty_code) for value in values)
    if not materialized:
        raise InvariantViolation(empty_code)
    if len(materialized) != len(set(materialized)):
        raise InvariantViolation(duplicate_code)
    return materialized


@dataclass(frozen=True, slots=True)
class MetricDistribution:
    unit: str
    p05: Decimal
    p50: Decimal
    p95: Decimal
    sample_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit", _text(self.unit, "MISSING_METRIC_UNIT"))
        p05 = _decimal(self.p05, "INVALID_METRIC_DISTRIBUTION")
        p50 = _decimal(self.p50, "INVALID_METRIC_DISTRIBUTION")
        p95 = _decimal(self.p95, "INVALID_METRIC_DISTRIBUTION")
        if min(p05, p50, p95) < 0:
            raise InvariantViolation("NEGATIVE_METRIC_DISTRIBUTION")
        if not p05 <= p50 <= p95:
            raise InvariantViolation("INVALID_METRIC_QUANTILES")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 2
        ):
            raise InvariantViolation("INSUFFICIENT_DISTRIBUTION_SAMPLES")
        object.__setattr__(self, "p05", p05)
        object.__setattr__(self, "p50", p50)
        object.__setattr__(self, "p95", p95)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "p05": self.p05,
            "p50": self.p50,
            "p95": self.p95,
            "sample_count": self.sample_count,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class MultipleTestingEvidence:
    tried_trial_ids: tuple[str, ...]
    pbo_trial_ids: tuple[str, ...]
    deflated_sharpe_trial_ids: tuple[str, ...]
    cscv_fold_count: int
    pbo_probability: Decimal
    deflated_sharpe: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tried_trial_ids",
            _unique_text_tuple(
                self.tried_trial_ids,
                empty_code="MISSING_TRIED_TRIAL_POPULATION",
                duplicate_code="DUPLICATE_TRIED_TRIAL",
            ),
        )
        object.__setattr__(
            self,
            "pbo_trial_ids",
            _unique_text_tuple(
                self.pbo_trial_ids,
                empty_code="MISSING_PBO_TRIAL_POPULATION",
                duplicate_code="DUPLICATE_PBO_TRIAL",
            ),
        )
        object.__setattr__(
            self,
            "deflated_sharpe_trial_ids",
            _unique_text_tuple(
                self.deflated_sharpe_trial_ids,
                empty_code="MISSING_DEFLATED_SHARPE_POPULATION",
                duplicate_code="DUPLICATE_DEFLATED_SHARPE_TRIAL",
            ),
        )
        if (
            isinstance(self.cscv_fold_count, bool)
            or not isinstance(self.cscv_fold_count, int)
            or self.cscv_fold_count < 2
        ):
            raise InvariantViolation("INSUFFICIENT_CSCV_FOLDS")
        probability = _decimal(
            self.pbo_probability,
            "INVALID_PBO_PROBABILITY",
        )
        if not Decimal("0") <= probability <= Decimal("1"):
            raise InvariantViolation("INVALID_PBO_PROBABILITY")
        object.__setattr__(self, "pbo_probability", probability)
        object.__setattr__(
            self,
            "deflated_sharpe",
            _decimal(self.deflated_sharpe, "INVALID_DEFLATED_SHARPE"),
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "tried_trial_ids": self.tried_trial_ids,
            "pbo_trial_ids": self.pbo_trial_ids,
            "deflated_sharpe_trial_ids": self.deflated_sharpe_trial_ids,
            "cscv_fold_count": self.cscv_fold_count,
            "pbo_probability": self.pbo_probability,
            "deflated_sharpe": self.deflated_sharpe,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    evidence_id: str
    search_id: str
    strategy_id: str
    strategy_version: int
    split_plan_sha256: str
    fold_ids: tuple[str, ...]
    purging_applied: bool
    embargo_ns: int
    baseline_kinds: tuple[BaselineKind, ...]
    multiple_testing: MultipleTestingEvidence
    cost_distribution: MetricDistribution | None
    capacity_distribution: MetricDistribution | None
    fill_uncertainty_distribution: MetricDistribution | None
    completed_fidelity_stages: tuple[FidelityStage, ...]
    claimed_fidelity_stage: FidelityStage
    synthetic_only: bool
    created_at_ns: int
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"
    strategy_edge_proven: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _text(self.evidence_id, "INVALID_VALIDATION_EVIDENCE_ID"),
        )
        object.__setattr__(
            self,
            "search_id",
            _text(self.search_id, "INVALID_VALIDATION_SEARCH_ID"),
        )
        object.__setattr__(
            self,
            "strategy_id",
            _text(self.strategy_id, "INVALID_VALIDATION_STRATEGY_ID"),
        )
        _positive_int(self.strategy_version, "INVALID_STRATEGY_VERSION")
        if not _HEX64.fullmatch(self.split_plan_sha256):
            raise InvariantViolation("INVALID_SPLIT_PLAN_SHA256")
        folds = _unique_text_tuple(
            self.fold_ids,
            empty_code="MISSING_VALIDATION_FOLDS",
            duplicate_code="DUPLICATE_VALIDATION_FOLD",
        )
        if len(folds) < 2:
            raise InvariantViolation("MULTIPLE_FOLDS_REQUIRED")
        object.__setattr__(self, "fold_ids", folds)
        if self.purging_applied is not True:
            raise InvariantViolation("PURGING_REQUIRED")
        if (
            isinstance(self.embargo_ns, bool)
            or not isinstance(self.embargo_ns, int)
            or self.embargo_ns <= 0
        ):
            raise InvariantViolation("EMBARGO_REQUIRED")
        baselines = tuple(self.baseline_kinds)
        if not baselines or any(
            not isinstance(item, BaselineKind) for item in baselines
        ):
            raise InvariantViolation("INVALID_BASELINE_KIND")
        if len(baselines) != len(set(baselines)):
            raise InvariantViolation("DUPLICATE_BASELINE_KIND")
        if BaselineKind.NO_TRADE not in baselines:
            raise InvariantViolation("NO_TRADE_BASELINE_REQUIRED")
        if not any(item is not BaselineKind.NO_TRADE for item in baselines):
            raise InvariantViolation("SIMPLE_BASELINE_REQUIRED")
        object.__setattr__(self, "baseline_kinds", baselines)
        if not isinstance(self.multiple_testing, MultipleTestingEvidence):
            raise InvariantViolation("MULTIPLE_TESTING_EVIDENCE_REQUIRED")
        if self.cost_distribution is None:
            raise InvariantViolation("COST_DISTRIBUTION_REQUIRED")
        if not isinstance(self.cost_distribution, MetricDistribution):
            raise InvariantViolation("INVALID_COST_DISTRIBUTION")
        if self.capacity_distribution is None:
            raise InvariantViolation("CAPACITY_DISTRIBUTION_REQUIRED")
        if not isinstance(self.capacity_distribution, MetricDistribution):
            raise InvariantViolation("INVALID_CAPACITY_DISTRIBUTION")
        if self.fill_uncertainty_distribution is None:
            raise InvariantViolation("FILL_UNCERTAINTY_DISTRIBUTION_REQUIRED")
        if not isinstance(
            self.fill_uncertainty_distribution,
            MetricDistribution,
        ):
            raise InvariantViolation("INVALID_FILL_UNCERTAINTY_DISTRIBUTION")
        stages = tuple(self.completed_fidelity_stages)
        if not stages or any(not isinstance(stage, FidelityStage) for stage in stages):
            raise InvariantViolation("MISSING_FIDELITY_STAGES")
        if len(stages) != len(set(stages)):
            raise InvariantViolation("DUPLICATE_FIDELITY_STAGE")
        expected = _FIDELITY_ORDER[: len(stages)]
        if stages != expected:
            raise InvariantViolation("FIDELITY_STAGE_GAP")
        object.__setattr__(self, "completed_fidelity_stages", stages)
        if not isinstance(self.claimed_fidelity_stage, FidelityStage):
            raise InvariantViolation("INVALID_CLAIMED_FIDELITY_STAGE")
        if self.claimed_fidelity_stage is not stages[-1]:
            raise InvariantViolation("FIDELITY_CLAIM_EXCEEDS_COMPLETION")
        if not isinstance(self.synthetic_only, bool):
            raise InvariantViolation("INVALID_SYNTHETIC_ONLY_FLAG")
        if self.synthetic_only and self.claimed_fidelity_stage is not FidelityStage.SYNTHETIC:
            raise InvariantViolation("SYNTHETIC_ONLY_FIDELITY_CLAIM")
        _nonnegative_int(self.created_at_ns, "INVALID_VALIDATION_CREATED_TIME")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("VALIDATION_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("VALIDATION_CANNOT_PROVE_PROFITABILITY")
        if self.strategy_edge_proven is not False:
            raise InvariantViolation("VALIDATION_DIAGNOSTICS_CANNOT_PROVE_EDGE")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "search_id": self.search_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "split_plan_sha256": self.split_plan_sha256,
            "fold_ids": self.fold_ids,
            "purging_applied": self.purging_applied,
            "embargo_ns": self.embargo_ns,
            "baseline_kinds": self.baseline_kinds,
            "multiple_testing": self.multiple_testing,
            "cost_distribution": self.cost_distribution,
            "capacity_distribution": self.capacity_distribution,
            "fill_uncertainty_distribution": self.fill_uncertainty_distribution,
            "completed_fidelity_stages": self.completed_fidelity_stages,
            "claimed_fidelity_stage": self.claimed_fidelity_stage,
            "synthetic_only": self.synthetic_only,
            "created_at_ns": self.created_at_ns,
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
            "strategy_edge_proven": self.strategy_edge_proven,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def validate_against_trials(
        self,
        trials: Iterable[TrialRecord],
    ) -> None:
        materialized = tuple(trials)
        if not materialized:
            raise InvariantViolation("EMPTY_VALIDATION_TRIAL_POPULATION")
        trial_ids = tuple(trial.trial_id for trial in materialized)
        if len(trial_ids) != len(set(trial_ids)):
            raise InvariantViolation("DUPLICATE_VALIDATION_TRIAL")
        for trial in materialized:
            if (
                trial.search_id != self.search_id
                or trial.strategy_id != self.strategy_id
                or trial.strategy_version != self.strategy_version
            ):
                raise InvariantViolation("VALIDATION_TRIAL_SCOPE_MISMATCH")
        expected = set(trial_ids)
        if set(self.multiple_testing.tried_trial_ids) != expected:
            raise InvariantViolation("TRIED_TRIAL_POPULATION_MISMATCH")
        if set(self.multiple_testing.pbo_trial_ids) != expected:
            raise InvariantViolation("PBO_TRIAL_POPULATION_MISMATCH")
        if set(self.multiple_testing.deflated_sharpe_trial_ids) != expected:
            raise InvariantViolation("DEFLATED_SHARPE_POPULATION_MISMATCH")
'''
    )
