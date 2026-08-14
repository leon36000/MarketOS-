"""Chronological, purged and embargoed validation contracts.

The split planner is intentionally model-agnostic.  It proves only temporal
isolation and complete sample accounting; it does not estimate predictive edge.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .canonical import canonical_sha256
from .errors import InvariantViolation

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
    anchored_train_start = config.first_test_start_ns - config.train_window_ns
    previous_embargoes: list[tuple[int, int]] = []
    folds: list[TemporalFold] = []

    for index in range(config.fold_count):
        test_start = config.first_test_start_ns + index * config.step_ns
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
            elif decision < anchored_train_start:
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
            train_start_ns=anchored_train_start,
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
