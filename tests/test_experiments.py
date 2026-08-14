from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from marketos.errors import DuplicateConflict, InvariantViolation
from marketos.experiments import (
    ExperimentLedger,
    SearchPlan,
    StrategyDefinition,
    TrialRecord,
    TrialStatus,
)


class ExperimentLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="marketos-experiment-ledger-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.path = self.temp / "experiments.sqlite"
        self.ledger = ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)

    @staticmethod
    def strategy(*, version: int = 1, hypothesis: str = "Short-horizon reversal after liquidity shock") -> StrategyDefinition:
        return StrategyDefinition(
            strategy_id="reversal-liquidity",
            version=version,
            hypothesis=hypothesis,
            mechanism="Temporary liquidity imbalance mean-reverts after forced flow",
            universe=("AAPL@XNAS", "MSFT@XNAS"),
            features=("spread-z@1", "signed-volume@1"),
            decision_rule="BUY when spread_z > 2 and signed_volume < -threshold",
            position_rule="risk-scaled capped long-only position",
            risk_budget={
                "gross_fraction": Decimal("0.10"),
                "single_name_fraction": Decimal("0.02"),
            },
            execution_policy="passive-first then cancel; no market sweep",
            abstention="abstain on stale data, halt, crossed market or missing borrow state",
            failure_modes=(
                "structural information event",
                "liquidity regime break",
                "execution cost exceeds gross signal",
            ),
            data_cutoffs={
                "features_available_at_ns": 1_000,
                "model_available_at_ns": 1_000,
                "memory_available_at_ns": 1_000,
                "prompt_available_at_ns": 1_000,
            },
            code_sha256="a" * 64,
            config_sha256="b" * 64,
        )

    @staticmethod
    def search_plan(*, version: int = 1, objective_metric: str = "DEFLATED_SHARPE") -> SearchPlan:
        return SearchPlan(
            search_id="search-reversal-001",
            version=version,
            strategy_id="reversal-liquidity",
            strategy_version=1,
            objective_metric=objective_metric,
            parameter_space={
                "spread_z": (Decimal("1.5"), Decimal("2.0"), Decimal("2.5")),
                "max_holding_bars": (1, 2, 3),
            },
            seeds=(7, 11, 19),
            max_trials=9,
            created_at_ns=1_100,
            hidden_holdout_id="holdout-2026-final",
        )

    @staticmethod
    def trial(
        trial_id: str,
        ordinal: int,
        status: TrialStatus,
        *,
        seed: int | None = None,
        metric: str | None = None,
        failure_reason: str | None = None,
    ) -> TrialRecord:
        metrics = {} if metric is None else {"deflated_sharpe": Decimal(metric)}
        return TrialRecord(
            trial_id=trial_id,
            search_id="search-reversal-001",
            strategy_id="reversal-liquidity",
            strategy_version=1,
            ordinal=ordinal,
            parameters={
                "spread_z": (
                    Decimal("1.5"),
                    Decimal("2.0"),
                    Decimal("2.5"),
                )[ordinal - 1],
                "max_holding_bars": 2,
            },
            seed=(7, 11, 19)[ordinal - 1] if seed is None else seed,
            status=status,
            started_at_ns=2_000 + ordinal * 10,
            completed_at_ns=2_005 + ordinal * 10,
            data_cutoff_ns=1_900,
            code_sha256="a" * 64,
            config_sha256="b" * 64,
            metrics=metrics,
            failure_reason=failure_reason,
        )

    def test_strategy_contract_is_complete_immutable_and_hash_stable(self) -> None:
        first = self.strategy()
        second = StrategyDefinition(
            **{
                **first.as_kwargs(),
                "risk_budget": {
                    "single_name_fraction": Decimal("0.02"),
                    "gross_fraction": Decimal("0.10"),
                },
                "data_cutoffs": {
                    "prompt_available_at_ns": 1_000,
                    "memory_available_at_ns": 1_000,
                    "model_available_at_ns": 1_000,
                    "features_available_at_ns": 1_000,
                },
            }
        )
        self.assertEqual(first.sha256(), second.sha256())
        self.assertEqual(first.universe, ("AAPL@XNAS", "MSFT@XNAS"))
        self.assertEqual(len(first.failure_modes), 3)
        with self.assertRaises(TypeError):
            first.risk_budget["gross_fraction"] = Decimal("0.20")
        with self.assertRaises(TypeError):
            first.data_cutoffs["features_available_at_ns"] = 2_000

    def test_strategy_versions_are_sequential_idempotent_and_conflict_safe(self) -> None:
        strategy = self.strategy()
        self.assertTrue(self.ledger.append_strategy(strategy))
        self.assertFalse(self.ledger.append_strategy(strategy))
        with self.assertRaises(DuplicateConflict):
            self.ledger.append_strategy(self.strategy(hypothesis="post-selected replacement"))
        with self.assertRaisesRegex(InvariantViolation, "STRATEGY_VERSION_SEQUENCE"):
            self.ledger.append_strategy(self.strategy(version=3))
        revised = self.strategy(version=2, hypothesis="Falsifiable revised mechanism")
        self.assertTrue(self.ledger.append_strategy(revised))
        self.assertEqual(self.ledger.strategy_history("reversal-liquidity"), (strategy, revised))

    def test_search_metric_and_stopping_plan_are_versioned_not_silently_changed(self) -> None:
        self.ledger.append_strategy(self.strategy())
        plan = self.search_plan()
        self.assertTrue(self.ledger.append_search_plan(plan))
        self.assertFalse(self.ledger.append_search_plan(plan))
        with self.assertRaises(DuplicateConflict):
            self.ledger.append_search_plan(self.search_plan(objective_metric="RAW_SHARPE"))
        revised = self.search_plan(version=2, objective_metric="PBO_ADJUSTED_SCORE")
        self.assertTrue(self.ledger.append_search_plan(revised))
        self.assertEqual(self.ledger.search_plan_history(plan.search_id), (plan, revised))

    def test_success_failure_and_abandonment_all_remain_queryable(self) -> None:
        self.ledger.append_strategy(self.strategy())
        self.ledger.append_search_plan(self.search_plan())
        trials = (
            self.trial("trial-success", 1, TrialStatus.SUCCEEDED, metric="0.42"),
            self.trial(
                "trial-failed",
                2,
                TrialStatus.FAILED,
                failure_reason="numerical instability",
            ),
            self.trial(
                "trial-abandoned",
                3,
                TrialStatus.ABANDONED,
                failure_reason="search budget exhausted",
            ),
        )
        for trial in trials:
            self.assertTrue(self.ledger.append_trial(trial))
        self.assertEqual(self.ledger.trials(), trials)
        self.assertEqual(self.ledger.trials(search_id="search-reversal-001"), trials)
        self.assertFalse(hasattr(self.ledger, "delete_trial"))

    def test_trial_status_contracts_fail_closed(self) -> None:
        with self.assertRaisesRegex(InvariantViolation, "SUCCEEDED_TRIAL_REQUIRES_METRICS"):
            self.trial("bad-success", 1, TrialStatus.SUCCEEDED)
        with self.assertRaisesRegex(InvariantViolation, "FAILED_TRIAL_REQUIRES_REASON"):
            self.trial("bad-failed", 1, TrialStatus.FAILED)
        with self.assertRaisesRegex(InvariantViolation, "ABANDONED_TRIAL_REQUIRES_REASON"):
            self.trial("bad-abandoned", 1, TrialStatus.ABANDONED)

    def test_trial_ordinal_collision_is_rejected(self) -> None:
        self.ledger.append_strategy(self.strategy())
        self.ledger.append_search_plan(self.search_plan())
        first = self.trial("trial-one", 1, TrialStatus.SUCCEEDED, metric="0.10")
        second = self.trial("trial-two", 1, TrialStatus.SUCCEEDED, metric="0.20")
        self.ledger.append_trial(first)
        with self.assertRaisesRegex(DuplicateConflict, "TRIAL_ORDINAL_CONFLICT"):
            self.ledger.append_trial(second)
        self.assertEqual(self.ledger.trials(), (first,))

    def test_direct_update_and_delete_are_forbidden_by_database_triggers(self) -> None:
        self.ledger.append_strategy(self.strategy())
        self.ledger.append_search_plan(self.search_plan())
        self.ledger.append_trial(
            self.trial("trial-locked", 1, TrialStatus.SUCCEEDED, metric="0.10")
        )
        connection = sqlite3.connect(self.path)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_TRIALS"):
            connection.execute(
                "UPDATE experiment_trials SET record_json = ? WHERE trial_id = ?",
                ("{}", "trial-locked"),
            )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "APPEND_ONLY_TRIALS"):
            connection.execute(
                "DELETE FROM experiment_trials WHERE trial_id = ?",
                ("trial-locked",),
            )
        connection.close()

    def test_idempotent_trial_redelivery_verifies_stored_content_first(self) -> None:
        self.ledger.append_strategy(self.strategy())
        self.ledger.append_search_plan(self.search_plan())
        trial = self.trial("trial-corrupt", 1, TrialStatus.SUCCEEDED, metric="0.10")
        self.ledger.append_trial(trial)
        self.ledger.close()
        connection = sqlite3.connect(self.path)
        connection.execute(
            "DROP TRIGGER experiment_trials_no_update"
        )
        connection.execute(
            "UPDATE experiment_trials SET record_json = ? WHERE trial_id = ? AND version = ?",
            ('{"trial_id":"tampered"}', trial.trial_id, 1),
        )
        connection.commit()
        connection.close()
        self.ledger = ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)
        with self.assertRaisesRegex(InvariantViolation, "TRIAL_RECORD_HASH_MISMATCH"):
            self.ledger.append_trial(trial)

    def test_reading_corrupted_strategy_record_fails(self) -> None:
        strategy = self.strategy()
        self.ledger.append_strategy(strategy)
        self.ledger.close()
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TRIGGER experiment_strategies_no_update")
        connection.execute(
            "UPDATE experiment_strategies SET record_json = ? WHERE strategy_id = ? AND version = ?",
            ('{"strategy_id":"tampered"}', strategy.strategy_id, strategy.version),
        )
        connection.commit()
        connection.close()
        self.ledger = ExperimentLedger(self.path)
        self.addCleanup(self.ledger.close)
        with self.assertRaisesRegex(InvariantViolation, "STRATEGY_RECORD_HASH_MISMATCH"):
            self.ledger.strategy_history(strategy.strategy_id)


if __name__ == "__main__":
    unittest.main()
