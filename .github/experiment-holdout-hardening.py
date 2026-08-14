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


path = "src/marketos/experiments.py"

replace_once(
    path,
    '''class TrialStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


@dataclass(frozen=True, slots=True)
class TrialRecord:
''',
    '''class DatasetRole(str, Enum):
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
''',
)

replace_once(
    path,
    '''            CREATE TRIGGER IF NOT EXISTS experiment_strategies_no_update
''',
    '''            CREATE TABLE IF NOT EXISTS experiment_access_receipts (
                ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT NOT NULL UNIQUE,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS experiment_strategies_no_update
''',
)

replace_once(
    path,
    '''            CREATE TRIGGER IF NOT EXISTS experiment_trials_no_delete
            BEFORE DELETE ON experiment_trials
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_TRIALS');
            END;
            """
''',
    '''            CREATE TRIGGER IF NOT EXISTS experiment_trials_no_delete
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
''',
)

replace_once(
    path,
    '''    def append_strategy(self, strategy: StrategyDefinition) -> bool:
''',
    '''    @staticmethod
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
''',
)

replace_once(
    path,
    '''        return tuple(self._trial_from_row(row) for row in rows)
''',
    '''        return tuple(self._trial_from_row(row) for row in rows)

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
''',
)
