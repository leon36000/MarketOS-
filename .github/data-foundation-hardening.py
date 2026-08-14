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


replace_once(
    "src/marketos/identity.py",
    '''        if assignment.entity_id not in self._instruments and assignment.entity_id not in self._venues:\n            raise InvariantViolation(f"UNKNOWN_IDENTIFIER_ENTITY:{assignment.entity_id}")\n''',
    '''        if (\n            assignment.entity_id not in self._instruments\n            and assignment.entity_id not in self._venues\n            and assignment.entity_id not in self._listings\n        ):\n            raise InvariantViolation(f"UNKNOWN_IDENTIFIER_ENTITY:{assignment.entity_id}")\n''',
)

replace_once(
    "src/marketos/corporate_actions.py",
    '''                and action.status is not ActionStatus.CANCELLED\n''',
    '''                and action.status not in {ActionStatus.CANCELLED, ActionStatus.QUARANTINED}\n''',
)

replace_once(
    "src/marketos/datafabric.py",
    '''from .errors import DuplicateConflict, InvariantViolation\n''',
    '''from .errors import DomainError, DuplicateConflict, InvariantViolation\n''',
)

replace_once(
    "src/marketos/datafabric.py",
    '''_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")\n\n\ndef _time''',
    '''_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")\n\n\nclass AmbiguousTemporalFact(DomainError):\n    """Raised when independent visible fact identities conflict for one key."""\n\n\ndef _time''',
)

replace_once(
    "src/marketos/datafabric.py",
    '''def _safe_relative(path: str) -> PurePosixPath:\n    candidate = PurePosixPath(path)\n    if (\n        not path\n        or candidate.is_absolute()\n        or ".." in candidate.parts\n        or "." in candidate.parts\n        or "\\\\" in path\n        or any(not part for part in candidate.parts)\n    ):\n        raise InvariantViolation(f"UNSAFE_DATASET_PATH:{path}")\n    return candidate\n''',
    '''def _safe_relative(path: str) -> PurePosixPath:\n    candidate = PurePosixPath(path)\n    if (\n        not path\n        or candidate.is_absolute()\n        or ".." in candidate.parts\n        or "\\\\" in path\n        or any(not part for part in candidate.parts)\n    ):\n        raise InvariantViolation(f"UNSAFE_DATASET_PATH:{path}")\n    if candidate.as_posix() != path:\n        raise InvariantViolation(f"NON_CANONICAL_DATASET_PATH:{path}")\n    return candidate\n''',
)

replace_once(
    "src/marketos/datafabric.py",
    '''        row = self._connection.execute(\n            """\n            SELECT * FROM temporal_facts\n            WHERE fact_key = ?\n              AND valid_from_ns <= ?\n              AND (valid_to_ns IS NULL OR ? < valid_to_ns)\n              AND available_to_strategy_at_ns <= ?\n            ORDER BY revision_time_ns DESC, version DESC\n            LIMIT 1\n            """,\n            (fact_key, economic_time_ns, economic_time_ns, knowledge_time_ns),\n        ).fetchone()\n        return None if row is None else self._from_row(row)\n''',
    '''        rows = self._connection.execute(\n            """\n            SELECT * FROM temporal_facts\n            WHERE fact_key = ?\n              AND valid_from_ns <= ?\n              AND (valid_to_ns IS NULL OR ? < valid_to_ns)\n              AND available_to_strategy_at_ns <= ?\n            ORDER BY fact_id, revision_time_ns DESC, version DESC\n            """,\n            (fact_key, economic_time_ns, economic_time_ns, knowledge_time_ns),\n        ).fetchall()\n        latest_by_fact_id: dict[str, sqlite3.Row] = {}\n        for row in rows:\n            latest_by_fact_id.setdefault(str(row["fact_id"]), row)\n        if len(latest_by_fact_id) > 1:\n            raise AmbiguousTemporalFact(\n                f"AMBIGUOUS_TEMPORAL_FACT:{fact_key}:{economic_time_ns}:{knowledge_time_ns}"\n            )\n        if not latest_by_fact_id:\n            return None\n        return self._from_row(next(iter(latest_by_fact_id.values())))\n''',
)

replace_once(
    "src/marketos/datafabric.py",
    '''        if lineage_complete is not True:\n            raise PublicationDenied("DATASET_LINEAGE_INCOMPLETE")\n        by_id = {policy.policy_id: policy for policy in policies}\n''',
    '''        if lineage_complete is not True:\n            raise PublicationDenied("DATASET_LINEAGE_INCOMPLETE")\n        policy_ids = [policy.policy_id for policy in policies]\n        if len(policy_ids) != len(set(policy_ids)):\n            raise PublicationDenied("DUPLICATE_RIGHTS_POLICY_ID")\n        by_id = {policy.policy_id: policy for policy in policies}\n''',
)
