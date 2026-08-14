"""Chronological, purged and embargoed validation contracts.

The split planner is intentionally model-agnostic.  It proves only temporal
isolation and complete sample accounting; it does not estimate predictive edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Iterable

from .canonical import canonical_sha256
from .errors import InvariantViolation
from .experiments import TrialRecord

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _positive_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvariantViolation(code)
    return value


@dataclass(frozen=True, slots=True)
class TemporalSample:
    sample_id: str
    decision_time_ns: int
    label_start_ns: int
    label_end_ns: int
    feature_available_at_ns: int
    model_available_at_ns: int
    memory_available_at_ns: int
    embedding_available_at_ns: int
    prompt_available_at_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sample_id",
            _text(self.sample_id, "INVALID_TEMPORAL_SAMPLE_ID"),
        )
        _nonnegative_int(self.decision_time_ns, "INVALID_SAMPLE_DECISION_TIME")
        _nonnegative_int(self.label_start_ns, "INVALID_LABEL_START")
        _nonnegative_int(self.label_end_ns, "INVALID_LABEL_END")
        if self.label_start_ns < self.decision_time_ns:
            raise InvariantViolation("LABEL_BEFORE_DECISION")
        if self.label_end_ns <= self.label_start_ns:
            raise InvariantViolation("INVALID_LABEL_INTERVAL")
        availability = (
            ("feature_available_at_ns", "FEATURE_LOOKAHEAD"),
            ("model_available_at_ns", "MODEL_LOOKAHEAD"),
            ("memory_available_at_ns", "MEMORY_LOOKAHEAD"),
            ("embedding_available_at_ns", "EMBEDDING_LOOKAHEAD"),
            ("prompt_available_at_ns", "PROMPT_LOOKAHEAD"),
        )
        for field, code in availability:
            value = getattr(self, field)
            _nonnegative_int(value, f"INVALID_{field.upper()}")
            if value > self.decision_time_ns:
                raise InvariantViolation(code)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "decision_time_ns": self.decision_time_ns,
            "label_start_ns": self.label_start_ns,
            "label_end_ns": self.label_end_ns,
            "feature_available_at_ns": self.feature_available_at_ns,
            "model_available_at_ns": self.model_available_at_ns,
            "memory_available_at_ns": self.memory_available_at_ns,
            "embedding_available_at_ns": self.embedding_available_at_ns,
            "prompt_available_at_ns": self.prompt_available_at_ns,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    first_test_start_ns: int
    train_window_ns: int
    test_window_ns: int
    step_ns: int
    embargo_ns: int
    fold_count: int
    min_train_samples: int
    min_test_samples: int

    def __post_init__(self) -> None:
        _nonnegative_int(self.first_test_start_ns, "INVALID_FIRST_TEST_START")
        _positive_int(self.train_window_ns, "INVALID_TRAIN_WINDOW")
        _positive_int(self.test_window_ns, "INVALID_TEST_WINDOW")
        _positive_int(self.step_ns, "INVALID_WALK_FORWARD_STEP")
        _nonnegative_int(self.embargo_ns, "INVALID_EMBARGO")
        _positive_int(self.fold_count, "INVALID_FOLD_COUNT")
        _positive_int(self.min_train_samples, "INVALID_MIN_TRAIN_SAMPLES")
        _positive_int(self.min_test_samples, "INVALID_MIN_TEST_SAMPLES")
        if self.first_test_start_ns < self.train_window_ns:
            raise InvariantViolation("INSUFFICIENT_INITIAL_TRAIN_WINDOW")
        if self.step_ns < self.test_window_ns + self.embargo_ns:
            raise InvariantViolation("WALK_FORWARD_STEP_TOO_SHORT")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "first_test_start_ns": self.first_test_start_ns,
            "train_window_ns": self.train_window_ns,
            "test_window_ns": self.test_window_ns,
            "step_ns": self.step_ns,
            "embargo_ns": self.embargo_ns,
            "fold_count": self.fold_count,
            "min_train_samples": self.min_train_samples,
            "min_test_samples": self.min_test_samples,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class TemporalFold:
    fold_id: str
    train_start_ns: int
    train_end_ns: int
    test_start_ns: int
    test_end_ns: int
    embargo_end_ns: int
    train_sample_ids: tuple[str, ...]
    test_sample_ids: tuple[str, ...]
    purged_sample_ids: tuple[str, ...]
    embargoed_sample_ids: tuple[str, ...]
    future_sample_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold_id", _text(self.fold_id, "INVALID_FOLD_ID"))
        for field in (
            "train_start_ns",
            "train_end_ns",
            "test_start_ns",
            "test_end_ns",
            "embargo_end_ns",
        ):
            _nonnegative_int(getattr(self, field), f"INVALID_{field.upper()}")
        if not self.train_start_ns <= self.train_end_ns <= self.test_start_ns:
            raise InvariantViolation("INVALID_TRAIN_TEST_ORDER")
        if self.test_end_ns <= self.test_start_ns:
            raise InvariantViolation("INVALID_TEST_INTERVAL")
        if self.embargo_end_ns < self.test_end_ns:
            raise InvariantViolation("INVALID_EMBARGO_INTERVAL")
        categories = (
            tuple(self.train_sample_ids),
            tuple(self.test_sample_ids),
            tuple(self.purged_sample_ids),
            tuple(self.embargoed_sample_ids),
            tuple(self.future_sample_ids),
        )
        flattened = [item for category in categories for item in category]
        if len(flattened) != len(set(flattened)):
            raise InvariantViolation("FOLD_SAMPLE_ACCOUNTING_OVERLAP")
        for field, value in zip(
            (
                "train_sample_ids",
                "test_sample_ids",
                "purged_sample_ids",
                "embargoed_sample_ids",
                "future_sample_ids",
            ),
            categories,
        ):
            object.__setattr__(self, field, value)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_start_ns": self.train_start_ns,
            "train_end_ns": self.train_end_ns,
            "test_start_ns": self.test_start_ns,
            "test_end_ns": self.test_end_ns,
            "embargo_end_ns": self.embargo_end_ns,
            "train_sample_ids": self.train_sample_ids,
            "test_sample_ids": self.test_sample_ids,
            "purged_sample_ids": self.purged_sample_ids,
            "embargoed_sample_ids": self.embargoed_sample_ids,
            "future_sample_ids": self.future_sample_ids,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class SplitPlan:
    config_sha256: str
    input_root_sha256: str
    sample_count: int
    folds: tuple[TemporalFold, ...]
    plan_sha256: str
    live_trading_state: str = "HARD_LOCKED"
    profitability_state: str = "UNPROVEN"

    def __post_init__(self) -> None:
        if not _HEX64.fullmatch(self.config_sha256):
            raise InvariantViolation("INVALID_SPLIT_CONFIG_SHA256")
        if not _HEX64.fullmatch(self.input_root_sha256):
            raise InvariantViolation("INVALID_SPLIT_INPUT_ROOT_SHA256")
        _positive_int(self.sample_count, "INVALID_SPLIT_SAMPLE_COUNT")
        folds = tuple(self.folds)
        if not folds:
            raise InvariantViolation("NO_VALID_WALK_FORWARD_FOLDS")
        object.__setattr__(self, "folds", folds)
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("SPLIT_PLAN_CANNOT_CHANGE_LIVE_LOCK")
        if self.profitability_state != "UNPROVEN":
            raise InvariantViolation("SPLIT_PLAN_CANNOT_PROVE_PROFITABILITY")
        expected = canonical_sha256(self.canonical_dict(include_hash=False))
        if self.plan_sha256 != expected:
            raise InvariantViolation("SPLIT_PLAN_SHA256_MISMATCH")

    def canonical_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "config_sha256": self.config_sha256,
            "input_root_sha256": self.input_root_sha256,
            "sample_count": self.sample_count,
            "folds": self.folds,
            "live_trading_state": self.live_trading_state,
            "profitability_state": self.profitability_state,
        }
        if include_hash:
            value["plan_sha256"] = self.plan_sha256
        return value

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


def _overlaps(
    start_a: int,
    end_a: int,
    start_b: int,
    end_b: int,
) -> bool:
    return start_a < end_b and end_a > start_b


def build_purged_walk_forward_plan(
    samples: Iterable[TemporalSample],
    config: WalkForwardConfig,
) -> SplitPlan:
    materialized = tuple(samples)
    if not materialized:
        raise InvariantViolation("EMPTY_TEMPORAL_SAMPLE_SET")
    sample_ids = [sample.sample_id for sample in materialized]
    if len(sample_ids) != len(set(sample_ids)):
        raise InvariantViolation("DUPLICATE_TEMPORAL_SAMPLE")
    ordered = tuple(
        sorted(
            materialized,
            key=lambda sample: (
                sample.decision_time_ns,
                sample.label_start_ns,
                sample.label_end_ns,
                sample.sample_id,
            ),
        )
    )
    previous_embargoes: list[tuple[int, int]] = []
    folds: list[TemporalFold] = []

    for index in range(config.fold_count):
        test_start = config.first_test_start_ns + index * config.step_ns
        train_start = test_start - config.train_window_ns
        test_end = test_start + config.test_window_ns
        embargo_end = test_end + config.embargo_ns
        train: list[str] = []
        test: list[str] = []
        purged: list[str] = []
        embargoed: list[str] = []
        future: list[str] = []

        for sample in ordered:
            decision = sample.decision_time_ns
            if test_start <= decision < test_end:
                test.append(sample.sample_id)
            elif decision >= test_end:
                future.append(sample.sample_id)
            elif any(start <= decision < end for start, end in previous_embargoes):
                embargoed.append(sample.sample_id)
            elif decision < train_start:
                purged.append(sample.sample_id)
            elif _overlaps(
                sample.label_start_ns,
                sample.label_end_ns,
                test_start,
                test_end,
            ):
                purged.append(sample.sample_id)
            else:
                train.append(sample.sample_id)

        if not test:
            raise InvariantViolation("NO_VALID_WALK_FORWARD_FOLDS")
        if (
            len(train) < config.min_train_samples
            or len(test) < config.min_test_samples
        ):
            raise InvariantViolation(
                f"INSUFFICIENT_FOLD_SAMPLES:fold={index + 1}:"
                f"train={len(train)}:test={len(test)}"
            )
        fold = TemporalFold(
            fold_id=f"fold-{index + 1:04d}",
            train_start_ns=train_start,
            train_end_ns=test_start,
            test_start_ns=test_start,
            test_end_ns=test_end,
            embargo_end_ns=embargo_end,
            train_sample_ids=tuple(train),
            test_sample_ids=tuple(test),
            purged_sample_ids=tuple(purged),
            embargoed_sample_ids=tuple(embargoed),
            future_sample_ids=tuple(future),
        )
        accounted = (
            len(fold.train_sample_ids)
            + len(fold.test_sample_ids)
            + len(fold.purged_sample_ids)
            + len(fold.embargoed_sample_ids)
            + len(fold.future_sample_ids)
        )
        if accounted != len(ordered):
            raise InvariantViolation("INCOMPLETE_FOLD_SAMPLE_ACCOUNTING")
        folds.append(fold)
        previous_embargoes.append((test_end, embargo_end))

    input_root = canonical_sha256(tuple(sample.sha256() for sample in ordered))
    payload = {
        "config_sha256": config.sha256(),
        "input_root_sha256": input_root,
        "sample_count": len(ordered),
        "folds": tuple(folds),
        "live_trading_state": "HARD_LOCKED",
        "profitability_state": "UNPROVEN",
    }
    return SplitPlan(
        config_sha256=config.sha256(),
        input_root_sha256=input_root,
        sample_count=len(ordered),
        folds=tuple(folds),
        plan_sha256=canonical_sha256(payload),
    )



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

    def assert_integrity(self) -> None:
        multiple_testing = MultipleTestingEvidence(
            tried_trial_ids=self.multiple_testing.tried_trial_ids,
            pbo_trial_ids=self.multiple_testing.pbo_trial_ids,
            deflated_sharpe_trial_ids=(
                self.multiple_testing.deflated_sharpe_trial_ids
            ),
            cscv_fold_count=self.multiple_testing.cscv_fold_count,
            pbo_probability=self.multiple_testing.pbo_probability,
            deflated_sharpe=self.multiple_testing.deflated_sharpe,
        )

        def rebuild_distribution(
            value: MetricDistribution | None,
        ) -> MetricDistribution | None:
            if value is None:
                return None
            return MetricDistribution(
                unit=value.unit,
                p05=value.p05,
                p50=value.p50,
                p95=value.p95,
                sample_count=value.sample_count,
            )

        ValidationEvidence(
            evidence_id=self.evidence_id,
            search_id=self.search_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            split_plan_sha256=self.split_plan_sha256,
            fold_ids=self.fold_ids,
            purging_applied=self.purging_applied,
            embargo_ns=self.embargo_ns,
            baseline_kinds=self.baseline_kinds,
            multiple_testing=multiple_testing,
            cost_distribution=rebuild_distribution(self.cost_distribution),
            capacity_distribution=rebuild_distribution(
                self.capacity_distribution
            ),
            fill_uncertainty_distribution=rebuild_distribution(
                self.fill_uncertainty_distribution
            ),
            completed_fidelity_stages=self.completed_fidelity_stages,
            claimed_fidelity_stage=self.claimed_fidelity_stage,
            synthetic_only=self.synthetic_only,
            created_at_ns=self.created_at_ns,
            live_trading_state=self.live_trading_state,
            profitability_state=self.profitability_state,
            strategy_edge_proven=self.strategy_edge_proven,
        )

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
