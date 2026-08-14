from __future__ import annotations

import unittest

from marketos.errors import InvariantViolation
from marketos.validation import (
    SplitPlan,
    TemporalSample,
    WalkForwardConfig,
    build_purged_walk_forward_plan,
)


class TemporalValidationTests(unittest.TestCase):
    @staticmethod
    def sample(
        sample_id: str,
        decision_ns: int,
        *,
        label_start_ns: int | None = None,
        label_end_ns: int | None = None,
        feature_available_at_ns: int | None = None,
        model_available_at_ns: int | None = None,
        memory_available_at_ns: int | None = None,
        embedding_available_at_ns: int | None = None,
        prompt_available_at_ns: int | None = None,
    ) -> TemporalSample:
        return TemporalSample(
            sample_id=sample_id,
            decision_time_ns=decision_ns,
            label_start_ns=(
                decision_ns if label_start_ns is None else label_start_ns
            ),
            label_end_ns=(
                decision_ns + 5 if label_end_ns is None else label_end_ns
            ),
            feature_available_at_ns=(
                decision_ns
                if feature_available_at_ns is None
                else feature_available_at_ns
            ),
            model_available_at_ns=(
                decision_ns
                if model_available_at_ns is None
                else model_available_at_ns
            ),
            memory_available_at_ns=(
                decision_ns
                if memory_available_at_ns is None
                else memory_available_at_ns
            ),
            embedding_available_at_ns=(
                decision_ns
                if embedding_available_at_ns is None
                else embedding_available_at_ns
            ),
            prompt_available_at_ns=(
                decision_ns
                if prompt_available_at_ns is None
                else prompt_available_at_ns
            ),
        )

    @staticmethod
    def config(**overrides) -> WalkForwardConfig:
        values = dict(
            first_test_start_ns=100,
            train_window_ns=100,
            test_window_ns=20,
            step_ns=30,
            embargo_ns=10,
            fold_count=2,
            min_train_samples=2,
            min_test_samples=1,
        )
        values.update(overrides)
        return WalkForwardConfig(**values)

    def baseline_samples(self) -> tuple[TemporalSample, ...]:
        return (
            self.sample("train-10", 10),
            self.sample("train-40", 40),
            self.sample("purged-95", 95, label_end_ns=105),
            self.sample("test-105", 105),
            self.sample("embargo-125", 125),
            self.sample("test-135", 135),
            self.sample("future-160", 160),
        )

    def test_plan_is_deterministic_independent_of_input_order(self) -> None:
        samples = self.baseline_samples()
        first = build_purged_walk_forward_plan(samples, self.config())
        second = build_purged_walk_forward_plan(
            tuple(reversed(samples)),
            self.config(),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.sha256(), second.sha256())
        self.assertEqual(first.live_trading_state, "HARD_LOCKED")
        self.assertEqual(len(first.folds), 2)

    def test_first_fold_purges_overlapping_labels_and_records_future_samples(self) -> None:
        plan = build_purged_walk_forward_plan(
            self.baseline_samples(),
            self.config(),
        )
        fold = plan.folds[0]
        self.assertEqual(fold.test_start_ns, 100)
        self.assertEqual(fold.test_end_ns, 120)
        self.assertEqual(fold.train_sample_ids, ("train-10", "train-40"))
        self.assertEqual(fold.test_sample_ids, ("test-105",))
        self.assertEqual(fold.purged_sample_ids, ("purged-95",))
        self.assertEqual(fold.embargoed_sample_ids, ())
        self.assertEqual(
            fold.future_sample_ids,
            ("embargo-125", "test-135", "future-160"),
        )

    def test_second_fold_excludes_prior_post_test_embargo(self) -> None:
        plan = build_purged_walk_forward_plan(
            self.baseline_samples(),
            self.config(),
        )
        fold = plan.folds[1]
        self.assertEqual(fold.test_start_ns, 130)
        self.assertEqual(fold.test_end_ns, 150)
        self.assertIn("embargo-125", fold.embargoed_sample_ids)
        self.assertEqual(fold.test_sample_ids, ("test-135",))
        self.assertNotIn("embargo-125", fold.train_sample_ids)
        self.assertNotIn("test-105", fold.embargoed_sample_ids)

    def test_every_fold_accounts_for_every_sample_exactly_once(self) -> None:
        samples = self.baseline_samples()
        plan = build_purged_walk_forward_plan(samples, self.config())
        expected = {sample.sample_id for sample in samples}
        for fold in plan.folds:
            categories = (
                fold.train_sample_ids,
                fold.test_sample_ids,
                fold.purged_sample_ids,
                fold.embargoed_sample_ids,
                fold.future_sample_ids,
            )
            flattened = [item for category in categories for item in category]
            self.assertEqual(set(flattened), expected)
            self.assertEqual(len(flattened), len(set(flattened)))

    def test_train_and_test_are_strictly_chronological_and_disjoint(self) -> None:
        plan = build_purged_walk_forward_plan(
            self.baseline_samples(),
            self.config(),
        )
        for fold in plan.folds:
            self.assertLess(fold.train_end_ns, fold.test_end_ns)
            self.assertLessEqual(fold.train_end_ns, fold.test_start_ns)
            self.assertTrue(
                set(fold.train_sample_ids).isdisjoint(fold.test_sample_ids)
            )
        self.assertLessEqual(
            plan.folds[0].test_end_ns + self.config().embargo_ns,
            plan.folds[1].test_start_ns,
        )

    def test_feature_model_memory_embedding_and_prompt_lookahead_are_rejected(self) -> None:
        fields = (
            ("feature_available_at_ns", "FEATURE_LOOKAHEAD"),
            ("model_available_at_ns", "MODEL_LOOKAHEAD"),
            ("memory_available_at_ns", "MEMORY_LOOKAHEAD"),
            ("embedding_available_at_ns", "EMBEDDING_LOOKAHEAD"),
            ("prompt_available_at_ns", "PROMPT_LOOKAHEAD"),
        )
        for field, error in fields:
            with self.subTest(field=field):
                with self.assertRaisesRegex(InvariantViolation, error):
                    self.sample(
                        f"lookahead-{field}",
                        100,
                        **{field: 101},
                    )

    def test_label_interval_must_begin_at_or_after_decision_and_have_positive_width(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "LABEL_BEFORE_DECISION"):
            self.sample(
                "past-label",
                100,
                label_start_ns=99,
                label_end_ns=105,
            )
        with self.assertRaisesRegex(InvariantViolation, "INVALID_LABEL_INTERVAL"):
            self.sample(
                "zero-label",
                100,
                label_start_ns=100,
                label_end_ns=100,
            )

    def test_duplicate_sample_ids_are_rejected(self) -> None:
        sample = self.sample("duplicate", 10)
        with self.assertRaisesRegex(InvariantViolation, "DUPLICATE_TEMPORAL_SAMPLE"):
            build_purged_walk_forward_plan(
                (sample, sample),
                self.config(fold_count=1),
            )

    def test_overlapping_test_windows_or_embargo_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            InvariantViolation,
            "WALK_FORWARD_STEP_TOO_SHORT",
        ):
            self.config(step_ns=25)

    def test_impossible_fold_counts_and_sample_requirements_fail_closed(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "NO_VALID_WALK_FORWARD_FOLDS"):
            build_purged_walk_forward_plan(
                self.baseline_samples(),
                self.config(fold_count=4),
            )
        with self.assertRaisesRegex(InvariantViolation, "INSUFFICIENT_FOLD_SAMPLES"):
            build_purged_walk_forward_plan(
                self.baseline_samples(),
                self.config(min_train_samples=4),
            )

    def test_plan_input_root_changes_when_label_timing_changes(self) -> None:
        original = self.baseline_samples()
        revised = tuple(
            self.sample(
                sample.sample_id,
                sample.decision_time_ns,
                label_start_ns=sample.label_start_ns,
                label_end_ns=(
                    106
                    if sample.sample_id == "purged-95"
                    else sample.label_end_ns
                ),
            )
            for sample in original
        )
        first = build_purged_walk_forward_plan(original, self.config())
        second = build_purged_walk_forward_plan(revised, self.config())
        self.assertNotEqual(first.input_root_sha256, second.input_root_sha256)
        self.assertIsInstance(first, SplitPlan)


if __name__ == "__main__":
    unittest.main()
