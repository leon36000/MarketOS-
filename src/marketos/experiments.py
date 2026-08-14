"""Immutable strategy contracts and append-only experiment evidence.

This module implements the first C10 research-governance slice.  It preserves
strategy definitions, search plans and every terminal trial outcome.  It does
not select a strategy, prove financial edge or expose any live execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from types import MappingProxyType
from typing import Any, Mapping

from .canonical import canonical_json, canonical_sha256
from .errors import DuplicateConflict, InvariantViolation

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")


def _require_text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(code)
    return value.strip()


def _require_id(value: str, code: str) -> str:
    normalized = _require_text(value, code)
    if not _SAFE_ID.fullmatch(normalized):
        raise InvariantViolation(code)
    return normalized


def _positive_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvariantViolation(code)
    return value


def _nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _require_sha256(value: str, code: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise InvariantViolation(code)
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen = {
            str(key): _freeze(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(
            sorted(
                (_freeze(item) for item in value),
                key=canonical_json,
            )
        )
    if isinstance(value, float):
        raise InvariantViolation("FLOAT_FORBIDDEN")
    canonical_sha256(value)
    return value


def _decode_canonical(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_canonical(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(str(value["$decimal"]))
        return {str(key): _decode_canonical(item) for key, item in value.items()}
    return value


def _load_record(text: str) -> Mapping[str, Any]:
    value = _decode_canonical(json.loads(text))
    if not isinstance(value, Mapping):
        raise ValueError("record must be an object")
    return value


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    version: int
    hypothesis: str
    mechanism: str
    universe: tuple[str, ...]
    features: tuple[str, ...]
    decision_rule: str
    position_rule: str
    risk_budget: Mapping[str, Any]
    execution_policy: str
    abstention: str
    failure_modes: tuple[str, ...]
    data_cutoffs: Mapping[str, int]
    code_sha256: str
    config_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "strategy_id",
            _require_id(self.strategy_id, "INVALID_STRATEGY_ID"),
        )
        _positive_int(self.version, "INVALID_STRATEGY_VERSION")
        for field_name, code in (
            ("hypothesis", "MISSING_STRATEGY_HYPOTHESIS"),
            ("mechanism", "MISSING_STRATEGY_MECHANISM"),
            ("decision_rule", "MISSING_STRATEGY_DECISION_RULE"),
            ("position_rule", "MISSING_STRATEGY_POSITION_RULE"),
            ("execution_policy", "MISSING_STRATEGY_EXECUTION_POLICY"),
            ("abstention", "MISSING_STRATEGY_ABSTENTION"),
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), code),
            )
        universe = tuple(_require_text(item, "INVALID_STRATEGY_UNIVERSE") for item in self.universe)
        features = tuple(_require_text(item, "INVALID_STRATEGY_FEATURE") for item in self.features)
        failures = tuple(_require_text(item, "INVALID_STRATEGY_FAILURE_MODE") for item in self.failure_modes)
        if not universe or len(universe) != len(set(universe)):
            raise InvariantViolation("INVALID_STRATEGY_UNIVERSE")
        if not features or len(features) != len(set(features)):
            raise InvariantViolation("INVALID_STRATEGY_FEATURES")
        if not failures or len(failures) != len(set(failures)):
            raise InvariantViolation("INVALID_STRATEGY_FAILURE_MODES")
        if not isinstance(self.risk_budget, Mapping) or not self.risk_budget:
            raise InvariantViolation("MISSING_STRATEGY_RISK_BUDGET")
        if not isinstance(self.data_cutoffs, Mapping) or not self.data_cutoffs:
            raise InvariantViolation("MISSING_STRATEGY_DATA_CUTOFFS")
        cutoffs: dict[str, int] = {}
        for key, value in self.data_cutoffs.items():
            normalized_key = _require_text(str(key), "INVALID_STRATEGY_DATA_CUTOFF")
            cutoffs[normalized_key] = _nonnegative_int(
                value,
                "INVALID_STRATEGY_DATA_CUTOFF",
            )
        object.__setattr__(self, "universe", universe)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "failure_modes", failures)
        object.__setattr__(self, "risk_budget", _freeze(self.risk_budget))
        object.__setattr__(self, "data_cutoffs", _freeze(cutoffs))
        _require_sha256(self.code_sha256, "INVALID_STRATEGY_CODE_SHA256")
        _require_sha256(self.config_sha256, "INVALID_STRATEGY_CONFIG_SHA256")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "hypothesis": self.hypothesis,
            "mechanism": self.mechanism,
            "universe": self.universe,
            "features": self.features,
            "decision_rule": self.decision_rule,
            "position_rule": self.position_rule,
            "risk_budget": self.risk_budget,
            "execution_policy": self.execution_policy,
            "abstention": self.abstention,
            "failure_modes": self.failure_modes,
            "data_cutoffs": self.data_cutoffs,
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def as_kwargs(self) -> dict[str, object]:
        return dict(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class SearchPlan:
    search_id: str
    version: int
    strategy_id: str
    strategy_version: int
    objective_metric: str
    parameter_space: Mapping[str, Any]
    seeds: tuple[int, ...]
    max_trials: int
    created_at_ns: int
    hidden_holdout_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "search_id", _require_id(self.search_id, "INVALID_SEARCH_ID"))
        object.__setattr__(
            self,
            "strategy_id",
            _require_id(self.strategy_id, "INVALID_STRATEGY_ID"),
        )
        _positive_int(self.version, "INVALID_SEARCH_PLAN_VERSION")
        _positive_int(self.strategy_version, "INVALID_STRATEGY_VERSION")
        object.__setattr__(
            self,
            "objective_metric",
            _require_text(self.objective_metric, "MISSING_SEARCH_OBJECTIVE"),
        )
        if not isinstance(self.parameter_space, Mapping) or not self.parameter_space:
            raise InvariantViolation("MISSING_PARAMETER_SPACE")
        seeds = tuple(self.seeds)
        if not seeds or len(seeds) != len(set(seeds)):
            raise InvariantViolation("INVALID_SEARCH_SEEDS")
        for seed in seeds:
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise InvariantViolation("INVALID_SEARCH_SEEDS")
        _positive_int(self.max_trials, "INVALID_MAX_TRIALS")
        _nonnegative_int(self.created_at_ns, "INVALID_SEARCH_CREATED_TIME")
        object.__setattr__(
            self,
            "hidden_holdout_id",
            _require_id(self.hidden_holdout_id, "MISSING_HIDDEN_HOLDOUT_ID"),
        )
        object.__setattr__(self, "parameter_space", _freeze(self.parameter_space))
        object.__setattr__(self, "seeds", seeds)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "search_id": self.search_id,
            "version": self.version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "objective_metric": self.objective_metric,
            "parameter_space": self.parameter_space,
            "seeds": self.seeds,
            "max_trials": self.max_trials,
            "created_at_ns": self.created_at_ns,
            "hidden_holdout_id": self.hidden_holdout_id,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def as_kwargs(self) -> dict[str, object]:
        return dict(self.canonical_dict())


class DatasetRole(str, Enum):
    CANDIDATE_GENERATOR = "CANDIDATE_GENERATOR"
    OPTIMIZER = "OPTIMIZER"
    MODEL_COUNCIL = "MODEL_COUNCIL"
    PROMPT_SYSTEM = "PROMPT_SYSTEM"
    EMBEDDING_SYSTEM = "EMBEDDING_SYSTEM"
    MEMORY_SYSTEM = "MEMORY_SYSTEM"
    INDEPENDENT_EVALUATOR = "INDEPENDENT_EVALUATOR"


class DatasetPartition(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    HIDDEN_HOLDOUT = "HIDDEN_HOLDOUT"


@dataclass(frozen=True, slots=True)
class AccessDecision:
    role: DatasetRole
    partition: DatasetPartition
    purpose: str
    requested_at_ns: int
    allowed: bool
    reason: str
    policy_id: str
    policy_version: int
    hidden_holdout_id: str
    policy_sha256: str
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        if not isinstance(self.role, DatasetRole):
            raise InvariantViolation("INVALID_DATASET_ROLE")
        if not isinstance(self.partition, DatasetPartition):
            raise InvariantViolation("INVALID_DATASET_PARTITION")
        object.__setattr__(
            self,
            "purpose",
            _require_text(self.purpose, "MISSING_DATASET_ACCESS_PURPOSE"),
        )
        _nonnegative_int(self.requested_at_ns, "INVALID_ACCESS_REQUEST_TIME")
        if not isinstance(self.allowed, bool):
            raise InvariantViolation("INVALID_ACCESS_DECISION")
        object.__setattr__(
            self,
            "reason",
            _require_text(self.reason, "MISSING_ACCESS_DECISION_REASON"),
        )
        object.__setattr__(
            self,
            "policy_id",
            _require_id(self.policy_id, "INVALID_ACCESS_POLICY_ID"),
        )
        _positive_int(self.policy_version, "INVALID_ACCESS_POLICY_VERSION")
        object.__setattr__(
            self,
            "hidden_holdout_id",
            _require_id(self.hidden_holdout_id, "MISSING_HIDDEN_HOLDOUT_ID"),
        )
        _require_sha256(self.policy_sha256, "INVALID_ACCESS_POLICY_SHA256")
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("ACCESS_DECISION_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "partition": self.partition,
            "purpose": self.purpose,
            "requested_at_ns": self.requested_at_ns,
            "allowed": self.allowed,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "hidden_holdout_id": self.hidden_holdout_id,
            "policy_sha256": self.policy_sha256,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class DatasetAccessPolicy:
    policy_id: str
    version: int
    hidden_holdout_id: str
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_id",
            _require_id(self.policy_id, "INVALID_ACCESS_POLICY_ID"),
        )
        _positive_int(self.version, "INVALID_ACCESS_POLICY_VERSION")
        object.__setattr__(
            self,
            "hidden_holdout_id",
            _require_id(self.hidden_holdout_id, "MISSING_HIDDEN_HOLDOUT_ID"),
        )
        if self.live_trading_state != "HARD_LOCKED":
            raise InvariantViolation("ACCESS_POLICY_CANNOT_CHANGE_LIVE_LOCK")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "hidden_holdout_id": self.hidden_holdout_id,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def authorize(
        self,
        *,
        role: DatasetRole,
        partition: DatasetPartition,
        purpose: str,
        requested_at_ns: int,
    ) -> AccessDecision:
        if not isinstance(role, DatasetRole):
            raise InvariantViolation("INVALID_DATASET_ROLE")
        if not isinstance(partition, DatasetPartition):
            raise InvariantViolation("INVALID_DATASET_PARTITION")
        normalized_purpose = _require_text(
            purpose,
            "MISSING_DATASET_ACCESS_PURPOSE",
        )
        _nonnegative_int(requested_at_ns, "INVALID_ACCESS_REQUEST_TIME")
        if partition is DatasetPartition.HIDDEN_HOLDOUT:
            if role is not DatasetRole.INDEPENDENT_EVALUATOR:
                allowed = False
                reason = "HIDDEN_HOLDOUT_ACCESS_FORBIDDEN"
            elif normalized_purpose != "FINAL_EVALUATION":
                allowed = False
                reason = "HIDDEN_HOLDOUT_PURPOSE_FORBIDDEN"
            else:
                allowed = True
                reason = "INDEPENDENT_FINAL_EVALUATION"
        else:
            allowed = True
            reason = "NON_HOLDOUT_ACCESS"
        return AccessDecision(
            role=role,
            partition=partition,
            purpose=normalized_purpose,
            requested_at_ns=requested_at_ns,
            allowed=allowed,
            reason=reason,
            policy_id=self.policy_id,
            policy_version=self.version,
            hidden_holdout_id=self.hidden_holdout_id,
            policy_sha256=self.sha256(),
        )


@dataclass(frozen=True, slots=True)
class AccessReceipt:
    receipt_id: str
    role: DatasetRole
    partition: DatasetPartition
    purpose: str
    requested_at_ns: int
    allowed: bool
    reason: str
    policy_id: str
    policy_version: int
    hidden_holdout_id: str
    policy_sha256: str
    decision_sha256: str
    live_trading_state: str = "HARD_LOCKED"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_id(self.receipt_id, "INVALID_ACCESS_RECEIPT_ID"),
        )
        decision = AccessDecision(
            role=self.role,
            partition=self.partition,
            purpose=self.purpose,
            requested_at_ns=self.requested_at_ns,
            allowed=self.allowed,
            reason=self.reason,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            hidden_holdout_id=self.hidden_holdout_id,
            policy_sha256=self.policy_sha256,
            live_trading_state=self.live_trading_state,
        )
        _require_sha256(self.decision_sha256, "INVALID_ACCESS_DECISION_SHA256")
        if self.decision_sha256 != decision.sha256():
            raise InvariantViolation("ACCESS_DECISION_SHA256_MISMATCH")

    @classmethod
    def from_decision(
        cls,
        *,
        receipt_id: str,
        decision: AccessDecision,
    ) -> "AccessReceipt":
        return cls(
            receipt_id=receipt_id,
            role=decision.role,
            partition=decision.partition,
            purpose=decision.purpose,
            requested_at_ns=decision.requested_at_ns,
            allowed=decision.allowed,
            reason=decision.reason,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            hidden_holdout_id=decision.hidden_holdout_id,
            policy_sha256=decision.policy_sha256,
            decision_sha256=decision.sha256(),
            live_trading_state=decision.live_trading_state,
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "role": self.role,
            "partition": self.partition,
            "purpose": self.purpose,
            "requested_at_ns": self.requested_at_ns,
            "allowed": self.allowed,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "hidden_holdout_id": self.hidden_holdout_id,
            "policy_sha256": self.policy_sha256,
            "decision_sha256": self.decision_sha256,
            "live_trading_state": self.live_trading_state,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class TrialStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


@dataclass(frozen=True, slots=True)
class TrialRecord:
    trial_id: str
    search_id: str
    strategy_id: str
    strategy_version: int
    ordinal: int
    parameters: Mapping[str, Any]
    seed: int
    status: TrialStatus
    started_at_ns: int
    completed_at_ns: int
    data_cutoff_ns: int
    code_sha256: str
    config_sha256: str
    metrics: Mapping[str, Any]
    failure_reason: str | None
    search_plan_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", _require_id(self.trial_id, "INVALID_TRIAL_ID"))
        object.__setattr__(self, "search_id", _require_id(self.search_id, "INVALID_SEARCH_ID"))
        object.__setattr__(
            self,
            "strategy_id",
            _require_id(self.strategy_id, "INVALID_STRATEGY_ID"),
        )
        _positive_int(self.strategy_version, "INVALID_STRATEGY_VERSION")
        _positive_int(self.search_plan_version, "INVALID_SEARCH_PLAN_VERSION")
        _positive_int(self.ordinal, "INVALID_TRIAL_ORDINAL")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise InvariantViolation("INVALID_TRIAL_SEED")
        if not isinstance(self.status, TrialStatus):
            raise InvariantViolation("INVALID_TRIAL_STATUS")
        _nonnegative_int(self.started_at_ns, "INVALID_TRIAL_START_TIME")
        _nonnegative_int(self.completed_at_ns, "INVALID_TRIAL_COMPLETION_TIME")
        _nonnegative_int(self.data_cutoff_ns, "INVALID_TRIAL_DATA_CUTOFF")
        if self.completed_at_ns < self.started_at_ns:
            raise InvariantViolation("TRIAL_COMPLETED_BEFORE_START")
        if self.data_cutoff_ns > self.started_at_ns:
            raise InvariantViolation("TRIAL_DATA_CUTOFF_AFTER_START")
        if not isinstance(self.parameters, Mapping) or not self.parameters:
            raise InvariantViolation("MISSING_TRIAL_PARAMETERS")
        if not isinstance(self.metrics, Mapping):
            raise InvariantViolation("INVALID_TRIAL_METRICS")
        metrics = _freeze(self.metrics)
        if self.status is TrialStatus.SUCCEEDED and not metrics:
            raise InvariantViolation("SUCCEEDED_TRIAL_REQUIRES_METRICS")
        if self.status is TrialStatus.FAILED and (
            self.failure_reason is None or not self.failure_reason.strip()
        ):
            raise InvariantViolation("FAILED_TRIAL_REQUIRES_REASON")
        if self.status is TrialStatus.ABANDONED and (
            self.failure_reason is None or not self.failure_reason.strip()
        ):
            raise InvariantViolation("ABANDONED_TRIAL_REQUIRES_REASON")
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _require_text(self.failure_reason, "INVALID_TRIAL_FAILURE_REASON"),
            )
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "metrics", metrics)
        _require_sha256(self.code_sha256, "INVALID_TRIAL_CODE_SHA256")
        _require_sha256(self.config_sha256, "INVALID_TRIAL_CONFIG_SHA256")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "trial_id": self.trial_id,
            "search_id": self.search_id,
            "search_plan_version": self.search_plan_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "ordinal": self.ordinal,
            "parameters": self.parameters,
            "seed": self.seed,
            "status": self.status,
            "started_at_ns": self.started_at_ns,
            "completed_at_ns": self.completed_at_ns,
            "data_cutoff_ns": self.data_cutoff_ns,
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
            "metrics": self.metrics,
            "failure_reason": self.failure_reason,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def as_kwargs(self) -> dict[str, object]:
        return dict(self.canonical_dict())


class ExperimentLedger:
    """SQLite append-only ledger for strategy research evidence."""

    live_trading_state = "HARD_LOCKED"
    profitability_state = "UNPROVEN"
    strategy_family_selected = False
    strategy_edge_proven = False
    champion_promoted = False

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiment_strategies (
                strategy_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                PRIMARY KEY(strategy_id, version)
            );
            CREATE TABLE IF NOT EXISTS experiment_search_plans (
                search_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                strategy_id TEXT NOT NULL,
                strategy_version INTEGER NOT NULL,
                hidden_holdout_id TEXT NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                PRIMARY KEY(search_id, version),
                FOREIGN KEY(strategy_id, strategy_version)
                    REFERENCES experiment_strategies(strategy_id, version)
            );
            CREATE TABLE IF NOT EXISTS experiment_trials (
                ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                trial_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1 CHECK(version = 1),
                search_id TEXT NOT NULL,
                search_plan_version INTEGER NOT NULL,
                strategy_id TEXT NOT NULL,
                strategy_version INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                UNIQUE(trial_id, version),
                UNIQUE(search_id, ordinal),
                FOREIGN KEY(search_id, search_plan_version)
                    REFERENCES experiment_search_plans(search_id, version),
                FOREIGN KEY(strategy_id, strategy_version)
                    REFERENCES experiment_strategies(strategy_id, version)
            );
            CREATE TABLE IF NOT EXISTS experiment_access_receipts (
                ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT NOT NULL UNIQUE,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS experiment_strategies_no_update
            BEFORE UPDATE ON experiment_strategies
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_STRATEGIES');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_strategies_no_delete
            BEFORE DELETE ON experiment_strategies
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_STRATEGIES');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_search_plans_no_update
            BEFORE UPDATE ON experiment_search_plans
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_SEARCH_PLANS');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_search_plans_no_delete
            BEFORE DELETE ON experiment_search_plans
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_SEARCH_PLANS');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_trials_no_update
            BEFORE UPDATE ON experiment_trials
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_TRIALS');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_trials_no_delete
            BEFORE DELETE ON experiment_trials
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_TRIALS');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_access_receipts_no_update
            BEFORE UPDATE ON experiment_access_receipts
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_ACCESS_RECEIPTS');
            END;
            CREATE TRIGGER IF NOT EXISTS experiment_access_receipts_no_delete
            BEFORE DELETE ON experiment_access_receipts
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_ACCESS_RECEIPTS');
            END;
            """
        )

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def __enter__(self) -> "ExperimentLedger":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _strategy_from_row(row: sqlite3.Row) -> StrategyDefinition:
        try:
            data = _load_record(str(row["record_json"]))
            strategy = StrategyDefinition(
                strategy_id=str(data["strategy_id"]),
                version=int(data["version"]),
                hypothesis=str(data["hypothesis"]),
                mechanism=str(data["mechanism"]),
                universe=tuple(str(item) for item in data["universe"]),
                features=tuple(str(item) for item in data["features"]),
                decision_rule=str(data["decision_rule"]),
                position_rule=str(data["position_rule"]),
                risk_budget=data["risk_budget"],
                execution_policy=str(data["execution_policy"]),
                abstention=str(data["abstention"]),
                failure_modes=tuple(str(item) for item in data["failure_modes"]),
                data_cutoffs=data["data_cutoffs"],
                code_sha256=str(data["code_sha256"]),
                config_sha256=str(data["config_sha256"]),
            )
        except Exception as exc:
            raise InvariantViolation(
                f"STRATEGY_RECORD_HASH_MISMATCH:{row['strategy_id']}:{row['version']}"
            ) from exc
        if (
            strategy.sha256() != str(row["record_sha256"])
            or canonical_json(strategy.canonical_dict()) != str(row["record_json"])
        ):
            raise InvariantViolation(
                f"STRATEGY_RECORD_HASH_MISMATCH:{strategy.strategy_id}:{strategy.version}"
            )
        return strategy

    @staticmethod
    def _search_plan_from_row(row: sqlite3.Row) -> SearchPlan:
        try:
            data = _load_record(str(row["record_json"]))
            plan = SearchPlan(
                search_id=str(data["search_id"]),
                version=int(data["version"]),
                strategy_id=str(data["strategy_id"]),
                strategy_version=int(data["strategy_version"]),
                objective_metric=str(data["objective_metric"]),
                parameter_space=data["parameter_space"],
                seeds=tuple(int(item) for item in data["seeds"]),
                max_trials=int(data["max_trials"]),
                created_at_ns=int(data["created_at_ns"]),
                hidden_holdout_id=str(data["hidden_holdout_id"]),
            )
        except Exception as exc:
            raise InvariantViolation(
                f"SEARCH_PLAN_RECORD_HASH_MISMATCH:{row['search_id']}:{row['version']}"
            ) from exc
        if (
            plan.sha256() != str(row["record_sha256"])
            or canonical_json(plan.canonical_dict()) != str(row["record_json"])
        ):
            raise InvariantViolation(
                f"SEARCH_PLAN_RECORD_HASH_MISMATCH:{plan.search_id}:{plan.version}"
            )
        return plan

    @staticmethod
    def _trial_from_row(row: sqlite3.Row) -> TrialRecord:
        try:
            data = _load_record(str(row["record_json"]))
            trial = TrialRecord(
                trial_id=str(data["trial_id"]),
                search_id=str(data["search_id"]),
                search_plan_version=int(data.get("search_plan_version", 1)),
                strategy_id=str(data["strategy_id"]),
                strategy_version=int(data["strategy_version"]),
                ordinal=int(data["ordinal"]),
                parameters=data["parameters"],
                seed=int(data["seed"]),
                status=TrialStatus(str(data["status"])),
                started_at_ns=int(data["started_at_ns"]),
                completed_at_ns=int(data["completed_at_ns"]),
                data_cutoff_ns=int(data["data_cutoff_ns"]),
                code_sha256=str(data["code_sha256"]),
                config_sha256=str(data["config_sha256"]),
                metrics=data["metrics"],
                failure_reason=(
                    None
                    if data.get("failure_reason") is None
                    else str(data["failure_reason"])
                ),
            )
        except Exception as exc:
            raise InvariantViolation(
                f"TRIAL_RECORD_HASH_MISMATCH:{row['trial_id']}:{row['version']}"
            ) from exc
        if (
            trial.sha256() != str(row["record_sha256"])
            or canonical_json(trial.canonical_dict()) != str(row["record_json"])
        ):
            raise InvariantViolation(
                f"TRIAL_RECORD_HASH_MISMATCH:{trial.trial_id}:{row['version']}"
            )
        return trial

    @staticmethod
    def _access_receipt_from_row(row: sqlite3.Row) -> AccessReceipt:
        try:
            data = _load_record(str(row["record_json"]))
            receipt = AccessReceipt(
                receipt_id=str(data["receipt_id"]),
                role=DatasetRole(str(data["role"])),
                partition=DatasetPartition(str(data["partition"])),
                purpose=str(data["purpose"]),
                requested_at_ns=int(data["requested_at_ns"]),
                allowed=bool(data["allowed"]),
                reason=str(data["reason"]),
                policy_id=str(data["policy_id"]),
                policy_version=int(data["policy_version"]),
                hidden_holdout_id=str(data["hidden_holdout_id"]),
                policy_sha256=str(data["policy_sha256"]),
                decision_sha256=str(data["decision_sha256"]),
                live_trading_state=str(data["live_trading_state"]),
            )
        except Exception as exc:
            raise InvariantViolation(
                f"ACCESS_RECEIPT_HASH_MISMATCH:{row['receipt_id']}"
            ) from exc
        if (
            receipt.sha256() != str(row["record_sha256"])
            or canonical_json(receipt.canonical_dict()) != str(row["record_json"])
        ):
            raise InvariantViolation(
                f"ACCESS_RECEIPT_HASH_MISMATCH:{receipt.receipt_id}"
            )
        return receipt

    def append_strategy(self, strategy: StrategyDefinition) -> bool:
        record_json = canonical_json(strategy.canonical_dict())
        digest = strategy.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM experiment_strategies WHERE strategy_id = ? AND version = ?",
                (strategy.strategy_id, strategy.version),
            ).fetchone()
            if existing is not None:
                stored = self._strategy_from_row(existing)
                if stored.sha256() != digest:
                    raise DuplicateConflict(
                        f"STRATEGY_VERSION_CONFLICT:{strategy.strategy_id}:{strategy.version}"
                    )
                self._connection.execute("COMMIT")
                return False
            latest = self._connection.execute(
                "SELECT MAX(version) AS version FROM experiment_strategies WHERE strategy_id = ?",
                (strategy.strategy_id,),
            ).fetchone()
            expected = 1 if latest is None or latest["version"] is None else int(latest["version"]) + 1
            if strategy.version != expected:
                raise InvariantViolation(
                    f"STRATEGY_VERSION_SEQUENCE:expected={expected}:actual={strategy.version}"
                )
            self._connection.execute(
                "INSERT INTO experiment_strategies(strategy_id, version, record_json, record_sha256) VALUES (?, ?, ?, ?)",
                (strategy.strategy_id, strategy.version, record_json, digest),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def strategy_history(self, strategy_id: str) -> tuple[StrategyDefinition, ...]:
        rows = self._connection.execute(
            "SELECT * FROM experiment_strategies WHERE strategy_id = ? ORDER BY version",
            (strategy_id,),
        ).fetchall()
        return tuple(self._strategy_from_row(row) for row in rows)

    def append_search_plan(self, plan: SearchPlan) -> bool:
        record_json = canonical_json(plan.canonical_dict())
        digest = plan.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            strategy_row = self._connection.execute(
                "SELECT * FROM experiment_strategies WHERE strategy_id = ? AND version = ?",
                (plan.strategy_id, plan.strategy_version),
            ).fetchone()
            if strategy_row is None:
                raise InvariantViolation(
                    f"UNKNOWN_SEARCH_STRATEGY:{plan.strategy_id}:{plan.strategy_version}"
                )
            self._strategy_from_row(strategy_row)
            existing = self._connection.execute(
                "SELECT * FROM experiment_search_plans WHERE search_id = ? AND version = ?",
                (plan.search_id, plan.version),
            ).fetchone()
            if existing is not None:
                stored = self._search_plan_from_row(existing)
                if stored.sha256() != digest:
                    raise DuplicateConflict(
                        f"SEARCH_PLAN_VERSION_CONFLICT:{plan.search_id}:{plan.version}"
                    )
                self._connection.execute("COMMIT")
                return False
            latest = self._connection.execute(
                "SELECT * FROM experiment_search_plans WHERE search_id = ? ORDER BY version DESC LIMIT 1",
                (plan.search_id,),
            ).fetchone()
            expected = 1 if latest is None else int(latest["version"]) + 1
            if plan.version != expected:
                raise InvariantViolation(
                    f"SEARCH_PLAN_VERSION_SEQUENCE:expected={expected}:actual={plan.version}"
                )
            if latest is not None:
                previous = self._search_plan_from_row(latest)
                if (
                    plan.strategy_id,
                    plan.strategy_version,
                    plan.hidden_holdout_id,
                ) != (
                    previous.strategy_id,
                    previous.strategy_version,
                    previous.hidden_holdout_id,
                ):
                    raise InvariantViolation("SEARCH_PLAN_IDENTITY_MUTATION")
            self._connection.execute(
                """
                INSERT INTO experiment_search_plans(
                    search_id, version, strategy_id, strategy_version,
                    hidden_holdout_id, record_json, record_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.search_id,
                    plan.version,
                    plan.strategy_id,
                    plan.strategy_version,
                    plan.hidden_holdout_id,
                    record_json,
                    digest,
                ),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def search_plan_history(self, search_id: str) -> tuple[SearchPlan, ...]:
        rows = self._connection.execute(
            "SELECT * FROM experiment_search_plans WHERE search_id = ? ORDER BY version",
            (search_id,),
        ).fetchall()
        return tuple(self._search_plan_from_row(row) for row in rows)

    def append_trial(self, trial: TrialRecord) -> bool:
        record_json = canonical_json(trial.canonical_dict())
        digest = trial.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM experiment_trials WHERE trial_id = ? AND version = 1",
                (trial.trial_id,),
            ).fetchone()
            if existing is not None:
                stored = self._trial_from_row(existing)
                if stored.sha256() != digest:
                    raise DuplicateConflict(f"TRIAL_ID_CONFLICT:{trial.trial_id}")
                self._connection.execute("COMMIT")
                return False
            plan_row = self._connection.execute(
                "SELECT * FROM experiment_search_plans WHERE search_id = ? AND version = ?",
                (trial.search_id, trial.search_plan_version),
            ).fetchone()
            if plan_row is None:
                raise InvariantViolation(
                    f"UNKNOWN_TRIAL_SEARCH_PLAN:{trial.search_id}:{trial.search_plan_version}"
                )
            plan = self._search_plan_from_row(plan_row)
            if (
                trial.strategy_id,
                trial.strategy_version,
            ) != (
                plan.strategy_id,
                plan.strategy_version,
            ):
                raise InvariantViolation("TRIAL_STRATEGY_MISMATCH")
            ordinal_row = self._connection.execute(
                "SELECT trial_id FROM experiment_trials WHERE search_id = ? AND ordinal = ?",
                (trial.search_id, trial.ordinal),
            ).fetchone()
            if ordinal_row is not None:
                raise DuplicateConflict(
                    f"TRIAL_ORDINAL_CONFLICT:{trial.search_id}:{trial.ordinal}"
                )
            try:
                self._connection.execute(
                    """
                    INSERT INTO experiment_trials(
                        trial_id, version, search_id, search_plan_version,
                        strategy_id, strategy_version, ordinal, status,
                        record_json, record_sha256
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trial.trial_id,
                        trial.search_id,
                        trial.search_plan_version,
                        trial.strategy_id,
                        trial.strategy_version,
                        trial.ordinal,
                        trial.status.value,
                        record_json,
                        digest,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "experiment_trials.search_id, experiment_trials.ordinal" in str(exc):
                    raise DuplicateConflict(
                        f"TRIAL_ORDINAL_CONFLICT:{trial.search_id}:{trial.ordinal}"
                    ) from exc
                raise
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def trials(self, search_id: str | None = None) -> tuple[TrialRecord, ...]:
        if search_id is None:
            rows = self._connection.execute(
                "SELECT * FROM experiment_trials ORDER BY ledger_sequence"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM experiment_trials WHERE search_id = ? ORDER BY ledger_sequence",
                (search_id,),
            ).fetchall()
        return tuple(self._trial_from_row(row) for row in rows)

    def append_access_receipt(self, receipt: AccessReceipt) -> bool:
        record_json = canonical_json(receipt.canonical_dict())
        digest = receipt.sha256()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM experiment_access_receipts WHERE receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone()
            if existing is not None:
                stored = self._access_receipt_from_row(existing)
                if stored.sha256() != digest:
                    raise DuplicateConflict(
                        f"ACCESS_RECEIPT_ID_CONFLICT:{receipt.receipt_id}"
                    )
                self._connection.execute("COMMIT")
                return False
            self._connection.execute(
                """
                INSERT INTO experiment_access_receipts(
                    receipt_id, record_json, record_sha256
                ) VALUES (?, ?, ?)
                """,
                (receipt.receipt_id, record_json, digest),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def access_receipts(self) -> tuple[AccessReceipt, ...]:
        rows = self._connection.execute(
            "SELECT * FROM experiment_access_receipts ORDER BY ledger_sequence"
        ).fetchall()
        return tuple(self._access_receipt_from_row(row) for row in rows)
