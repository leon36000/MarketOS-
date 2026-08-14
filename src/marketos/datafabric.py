"""Local conformance backend for immutable evidence and temporal datasets.

This module deliberately does not select a production lake, temporal database or
object store.  It implements the C2/C3 contracts with the Python standard
library so higher layers can be built and tested without weakening truth or
rights boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .canonical import canonical_json, canonical_sha256
from .errors import DomainError, DuplicateConflict, InvariantViolation
from .rights import RightsPolicy

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class AmbiguousTemporalFact(DomainError):
    """Raised when independent visible fact identities conflict for one key."""


def _time(value: int, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_canonical_decode(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        return {key: _canonical_decode(item) for key, item in value.items()}
    return value


def _safe_relative(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or ".." in candidate.parts
        or "\\" in path
        or any(not part for part in candidate.parts)
    ):
        raise InvariantViolation(f"UNSAFE_DATASET_PATH:{path}")
    if candidate.as_posix() != path:
        raise InvariantViolation(f"NON_CANONICAL_DATASET_PATH:{path}")
    return candidate


@dataclass(frozen=True, slots=True)
class RetrievalReceipt:
    receipt_id: int
    content_sha256: str
    source_id: str
    retrieved_at_ns: int
    media_type: str
    rights_policy_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawEvidenceRef:
    content_sha256: str
    object_path: Path
    inserted: bool
    bytes_count: int


class RawEvidenceStore:
    """Content-addressed bytes plus an append-only retrieval ledger."""

    live_trading_state = "HARD_LOCKED"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.object_root = self.root / "objects" / "sha256"
        self.object_root.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.root / "retrievals.sqlite", isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS retrieval_receipts (
                receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_sha256 TEXT NOT NULL,
                source_id TEXT NOT NULL,
                retrieved_at_ns INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                rights_policy_ids_json TEXT NOT NULL
            )
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "RawEvidenceStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _path(self, content_sha256: str) -> Path:
        if not _HEX64.fullmatch(content_sha256):
            raise InvariantViolation("INVALID_CONTENT_SHA256")
        return self.object_root / content_sha256[:2] / content_sha256

    def put(
        self,
        data: bytes,
        *,
        source_id: str,
        retrieved_at_ns: int,
        media_type: str,
        rights_policy_ids: Iterable[str],
    ) -> RawEvidenceRef:
        if not isinstance(data, bytes):
            raise InvariantViolation("RAW_EVIDENCE_MUST_BE_BYTES")
        if not source_id.strip() or not media_type.strip():
            raise InvariantViolation("MISSING_RETRIEVAL_METADATA")
        _time(retrieved_at_ns, "INVALID_RETRIEVAL_TIME")
        policies = tuple(sorted(set(rights_policy_ids)))
        if not policies or any(not policy.strip() for policy in policies):
            raise InvariantViolation("MISSING_RIGHTS_POLICY")
        digest = _sha256_bytes(data)
        path = self._path(digest)
        inserted = not path.exists()
        if inserted:
            _atomic_write(path, data)
        elif _sha256_bytes(path.read_bytes()) != digest:
            raise InvariantViolation(f"RAW_EVIDENCE_HASH_MISMATCH:{digest}")
        self._connection.execute(
            """
            INSERT INTO retrieval_receipts(
                content_sha256, source_id, retrieved_at_ns, media_type,
                rights_policy_ids_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (digest, source_id, retrieved_at_ns, media_type, canonical_json(policies)),
        )
        return RawEvidenceRef(digest, path, inserted, len(data))

    def get(self, content_sha256: str) -> bytes:
        path = self._path(content_sha256)
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise InvariantViolation(f"RAW_EVIDENCE_NOT_FOUND:{content_sha256}") from exc
        if _sha256_bytes(data) != content_sha256:
            raise InvariantViolation(f"RAW_EVIDENCE_HASH_MISMATCH:{content_sha256}")
        return data

    def verify(self, content_sha256: str) -> bool:
        try:
            return _sha256_bytes(self._path(content_sha256).read_bytes()) == content_sha256
        except (FileNotFoundError, InvariantViolation):
            return False

    def receipts(self, content_sha256: str) -> tuple[RetrievalReceipt, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM retrieval_receipts
            WHERE content_sha256 = ? ORDER BY receipt_id
            """,
            (content_sha256,),
        ).fetchall()
        return tuple(
            RetrievalReceipt(
                receipt_id=int(row["receipt_id"]),
                content_sha256=str(row["content_sha256"]),
                source_id=str(row["source_id"]),
                retrieved_at_ns=int(row["retrieved_at_ns"]),
                media_type=str(row["media_type"]),
                rights_policy_ids=tuple(json.loads(row["rights_policy_ids_json"])),
            )
            for row in rows
        )


@dataclass(frozen=True, slots=True)
class TemporalFact:
    fact_id: str
    fact_key: str
    version: int
    valid_from_ns: int
    valid_to_ns: int | None
    available_to_strategy_at_ns: int
    revision_time_ns: int
    source_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.fact_id.strip() or not self.fact_key.strip() or not self.source_id.strip():
            raise InvariantViolation("MISSING_TEMPORAL_FACT_IDENTITY")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_FACT_VERSION")
        _time(self.valid_from_ns, "INVALID_FACT_VALID_FROM")
        if self.valid_to_ns is not None:
            _time(self.valid_to_ns, "INVALID_FACT_VALID_TO")
            if self.valid_to_ns <= self.valid_from_ns:
                raise InvariantViolation("INVALID_FACT_VALID_INTERVAL")
        _time(self.available_to_strategy_at_ns, "INVALID_FACT_AVAILABLE_TIME")
        _time(self.revision_time_ns, "INVALID_FACT_REVISION_TIME")
        if not isinstance(self.payload, Mapping):
            raise InvariantViolation("FACT_PAYLOAD_MUST_BE_MAPPING")
        normalized = {str(key): value for key, value in self.payload.items()}
        canonical_sha256(normalized)
        object.__setattr__(self, "payload", MappingProxyType(dict(sorted(normalized.items()))))

    def canonical_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "fact_key": self.fact_key,
            "version": self.version,
            "valid_from_ns": self.valid_from_ns,
            "valid_to_ns": self.valid_to_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "revision_time_ns": self.revision_time_ns,
            "source_id": self.source_id,
            "payload": self.payload,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class TemporalFactStore:
    """SQLite reference backend for bitemporal fact revisions."""

    live_trading_state = "HARD_LOCKED"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS temporal_facts (
                fact_id TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                valid_from_ns INTEGER NOT NULL,
                valid_to_ns INTEGER,
                available_to_strategy_at_ns INTEGER NOT NULL,
                revision_time_ns INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                fact_sha256 TEXT NOT NULL,
                PRIMARY KEY(fact_id, version)
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_temporal_fact_query ON temporal_facts(fact_key, available_to_strategy_at_ns, valid_from_ns)"
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "TemporalFactStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TemporalFact:
        payload = _canonical_decode(json.loads(row["payload_json"]))
        return TemporalFact(
            fact_id=str(row["fact_id"]),
            fact_key=str(row["fact_key"]),
            version=int(row["version"]),
            valid_from_ns=int(row["valid_from_ns"]),
            valid_to_ns=None if row["valid_to_ns"] is None else int(row["valid_to_ns"]),
            available_to_strategy_at_ns=int(row["available_to_strategy_at_ns"]),
            revision_time_ns=int(row["revision_time_ns"]),
            source_id=str(row["source_id"]),
            payload=payload,
        )

    def append(self, fact: TemporalFact) -> bool:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT fact_sha256 FROM temporal_facts WHERE fact_id = ? AND version = ?",
                (fact.fact_id, fact.version),
            ).fetchone()
            digest = fact.sha256()
            if existing is not None:
                if existing["fact_sha256"] != digest:
                    raise DuplicateConflict(
                        f"FACT_VERSION_CONFLICT:{fact.fact_id}:{fact.version}"
                    )
                self._connection.execute("COMMIT")
                return False
            latest = self._connection.execute(
                "SELECT fact_key, version, revision_time_ns FROM temporal_facts WHERE fact_id = ? ORDER BY version DESC LIMIT 1",
                (fact.fact_id,),
            ).fetchone()
            expected = 1 if latest is None else int(latest["version"]) + 1
            if fact.version != expected:
                raise InvariantViolation(
                    f"FACT_VERSION_SEQUENCE:expected={expected}:actual={fact.version}"
                )
            if latest is not None:
                if latest["fact_key"] != fact.fact_key:
                    raise InvariantViolation("FACT_KEY_MUTATION")
                if fact.revision_time_ns < int(latest["revision_time_ns"]):
                    raise InvariantViolation("FACT_REVISION_TIME_REGRESSION")
            self._connection.execute(
                """
                INSERT INTO temporal_facts(
                    fact_id, fact_key, version, valid_from_ns, valid_to_ns,
                    available_to_strategy_at_ns, revision_time_ns, source_id,
                    payload_json, fact_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.fact_key,
                    fact.version,
                    fact.valid_from_ns,
                    fact.valid_to_ns,
                    fact.available_to_strategy_at_ns,
                    fact.revision_time_ns,
                    fact.source_id,
                    canonical_json(fact.payload),
                    digest,
                ),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def as_of(
        self,
        fact_key: str,
        *,
        economic_time_ns: int,
        knowledge_time_ns: int,
    ) -> TemporalFact | None:
        _time(economic_time_ns, "INVALID_ECONOMIC_TIME")
        _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        rows = self._connection.execute(
            """
            SELECT * FROM temporal_facts
            WHERE fact_key = ?
              AND valid_from_ns <= ?
              AND (valid_to_ns IS NULL OR ? < valid_to_ns)
              AND available_to_strategy_at_ns <= ?
            ORDER BY fact_id, revision_time_ns DESC, version DESC
            """,
            (fact_key, economic_time_ns, economic_time_ns, knowledge_time_ns),
        ).fetchall()
        latest_by_fact_id: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest_by_fact_id.setdefault(str(row["fact_id"]), row)
        if len(latest_by_fact_id) > 1:
            raise AmbiguousTemporalFact(
                f"AMBIGUOUS_TEMPORAL_FACT:{fact_key}:{economic_time_ns}:{knowledge_time_ns}"
            )
        if not latest_by_fact_id:
            return None
        return self._from_row(next(iter(latest_by_fact_id.values())))

    def history(self, fact_id: str) -> tuple[TemporalFact, ...]:
        rows = self._connection.execute(
            "SELECT * FROM temporal_facts WHERE fact_id = ? ORDER BY version",
            (fact_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    dataset_id: str
    version: str
    schema_id: str
    source_versions: tuple[str, ...]
    economic_cutoff_ns: int
    knowledge_cutoff_ns: int
    code_sha256: str
    config_sha256: str
    dependency_lock_sha256: str
    rights_policy_ids: tuple[str, ...]
    quality_report_id: str
    lineage_run_id: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.dataset_id, "INVALID_DATASET_ID"),
            (self.version, "INVALID_DATASET_VERSION"),
        ):
            if not _SAFE_ID.fullmatch(value):
                raise InvariantViolation(code)
        for value, code in (
            (self.schema_id, "MISSING_SCHEMA_ID"),
            (self.quality_report_id, "MISSING_QUALITY_REPORT_ID"),
            (self.lineage_run_id, "MISSING_LINEAGE_RUN_ID"),
        ):
            if not value.strip():
                raise InvariantViolation(code)
        if not self.source_versions or any(not value.strip() for value in self.source_versions):
            raise InvariantViolation("MISSING_SOURCE_VERSIONS")
        if not self.rights_policy_ids or any(not value.strip() for value in self.rights_policy_ids):
            raise InvariantViolation("MISSING_RIGHTS_POLICY_IDS")
        _time(self.economic_cutoff_ns, "INVALID_ECONOMIC_CUTOFF")
        _time(self.knowledge_cutoff_ns, "INVALID_KNOWLEDGE_CUTOFF")
        if self.knowledge_cutoff_ns < self.economic_cutoff_ns:
            raise InvariantViolation("KNOWLEDGE_CUTOFF_BEFORE_ECONOMIC_CUTOFF")
        for digest in (self.code_sha256, self.config_sha256, self.dependency_lock_sha256):
            if not _HEX64.fullmatch(digest):
                raise InvariantViolation("INVALID_DATASET_DEPENDENCY_SHA256")
        object.__setattr__(self, "source_versions", tuple(sorted(set(self.source_versions))))
        object.__setattr__(self, "rights_policy_ids", tuple(sorted(set(self.rights_policy_ids))))

    def canonical_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "schema_id": self.schema_id,
            "source_versions": self.source_versions,
            "economic_cutoff_ns": self.economic_cutoff_ns,
            "knowledge_cutoff_ns": self.knowledge_cutoff_ns,
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "rights_policy_ids": self.rights_policy_ids,
            "quality_report_id": self.quality_report_id,
            "lineage_run_id": self.lineage_run_id,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class PublicationDenied(InvariantViolation):
    """Raised when rights, quality or lineage gates block publication."""


@dataclass(frozen=True, slots=True)
class PublicationResult:
    dataset_id: str
    version: str
    content_root_sha256: str
    commit_path: Path
    inserted: bool
    manifest_sha256: str


class DatasetPublisher:
    """Stage, validate and atomically commit immutable dataset versions."""

    live_trading_state = "HARD_LOCKED"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.dataset_root = self.root / "datasets"
        self.staging_root = self.root / ".staging"
        self.dataset_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _admit(
        spec: DatasetSpec,
        policies: tuple[RightsPolicy, ...],
        *,
        quality_pass: bool,
        lineage_complete: bool,
    ) -> None:
        if quality_pass is not True:
            raise PublicationDenied("DATASET_QUALITY_GATE_FAILED")
        if lineage_complete is not True:
            raise PublicationDenied("DATASET_LINEAGE_INCOMPLETE")
        policy_ids = [policy.policy_id for policy in policies]
        if len(policy_ids) != len(set(policy_ids)):
            raise PublicationDenied("DUPLICATE_RIGHTS_POLICY_ID")
        by_id = {policy.policy_id: policy for policy in policies}
        if set(by_id) != set(spec.rights_policy_ids):
            raise PublicationDenied("DATASET_RIGHTS_POLICY_SET_MISMATCH")
        for policy in policies:
            for capability in ("storage", "historical_replay", "derived_data"):
                if not policy.allows(capability):
                    raise PublicationDenied(
                        f"DATASET_RIGHT_DENIED:{policy.policy_id}:{capability}"
                    )

    @staticmethod
    def _file_records(files: Mapping[str, bytes]) -> tuple[dict[str, object], ...]:
        if not files:
            raise InvariantViolation("EMPTY_DATASET")
        records: list[dict[str, object]] = []
        for raw_path, data in files.items():
            path = _safe_relative(raw_path)
            if not isinstance(data, bytes):
                raise InvariantViolation(f"DATASET_FILE_MUST_BE_BYTES:{raw_path}")
            records.append(
                {"path": path.as_posix(), "bytes": len(data), "sha256": _sha256_bytes(data)}
            )
        paths = [record["path"] for record in records]
        if len(paths) != len(set(paths)):
            raise InvariantViolation("DUPLICATE_DATASET_PATH")
        return tuple(sorted(records, key=lambda record: str(record["path"])))

    def publish(
        self,
        spec: DatasetSpec,
        files: Mapping[str, bytes],
        *,
        rights_policies: Iterable[RightsPolicy],
        quality_pass: bool,
        lineage_complete: bool,
    ) -> PublicationResult:
        policies = tuple(rights_policies)
        self._admit(
            spec,
            policies,
            quality_pass=quality_pass,
            lineage_complete=lineage_complete,
        )
        records = self._file_records(files)
        content_root = canonical_sha256(records)
        manifest = {
            **spec.canonical_dict(),
            "spec_sha256": spec.sha256(),
            "content_root_sha256": content_root,
            "files": records,
            "quality_pass": True,
            "lineage_complete": True,
            "rights_policy_sha256": tuple(sorted(policy.sha256() for policy in policies)),
            "live_trading_state": "HARD_LOCKED",
        }
        manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
        manifest_sha = _sha256_bytes(manifest_bytes)
        final_dir = self.dataset_root / spec.dataset_id / spec.version
        commit_path = final_dir / "COMMIT.json"
        if final_dir.exists():
            if not commit_path.is_file():
                raise InvariantViolation(f"PARTIAL_DATASET_VERSION:{spec.dataset_id}:{spec.version}")
            existing = commit_path.read_bytes()
            if existing != manifest_bytes:
                raise DuplicateConflict(
                    f"DATASET_VERSION_CONFLICT:{spec.dataset_id}:{spec.version}"
                )
            return PublicationResult(
                spec.dataset_id,
                spec.version,
                content_root,
                commit_path,
                False,
                manifest_sha,
            )

        stage = self.staging_root / f"{spec.dataset_id}-{spec.version}-{uuid4().hex}"
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for record in records:
                relative = PurePosixPath(str(record["path"]))
                data = files[str(record["path"])]
                destination = stage.joinpath(*relative.parts)
                _atomic_write(destination, data)
            _atomic_write(stage / "COMMIT.json", manifest_bytes)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, final_dir)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        return PublicationResult(
            spec.dataset_id,
            spec.version,
            content_root,
            commit_path,
            True,
            manifest_sha,
        )

    def list_versions(self, dataset_id: str) -> tuple[str, ...]:
        if not _SAFE_ID.fullmatch(dataset_id):
            raise InvariantViolation("INVALID_DATASET_ID")
        parent = self.dataset_root / dataset_id
        if not parent.is_dir():
            return ()
        return tuple(
            sorted(
                child.name
                for child in parent.iterdir()
                if child.is_dir() and (child / "COMMIT.json").is_file()
            )
        )


@dataclass(frozen=True, slots=True)
class BackupFile:
    path: str
    bytes_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BackupManifest:
    files: tuple[BackupFile, ...]
    content_root_sha256: str

    def canonical_dict(self) -> dict[str, object]:
        return {"files": self.files, "content_root_sha256": self.content_root_sha256}


@dataclass(frozen=True, slots=True)
class BackupVerification:
    ok: bool
    errors: tuple[str, ...]
    files_checked: int
    content_root_sha256: str


def _walk_files(root: Path) -> tuple[BackupFile, ...]:
    if not root.is_dir():
        raise InvariantViolation(f"BACKUP_ROOT_NOT_DIRECTORY:{root}")
    records: list[BackupFile] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InvariantViolation(f"BACKUP_SYMLINK_FORBIDDEN:{path.relative_to(root).as_posix()}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            records.append(BackupFile(relative, len(data), _sha256_bytes(data)))
    return tuple(records)


def create_backup_manifest(root: str | Path) -> BackupManifest:
    records = _walk_files(Path(root))
    content_root = canonical_sha256(tuple(record.__dict__ if hasattr(record, "__dict__") else {"path": record.path, "bytes_count": record.bytes_count, "sha256": record.sha256} for record in records))
    return BackupManifest(records, content_root)


def verify_backup_manifest(root: str | Path, manifest: BackupManifest) -> BackupVerification:
    root_path = Path(root)
    errors: list[str] = []
    try:
        actual = _walk_files(root_path)
    except InvariantViolation as exc:
        return BackupVerification(False, (str(exc),), 0, "")
    expected_by_path = {record.path: record for record in manifest.files}
    actual_by_path = {record.path: record for record in actual}
    for path in sorted(expected_by_path.keys() - actual_by_path.keys()):
        errors.append(f"MISSING_FILE:{path}")
    for path in sorted(actual_by_path.keys() - expected_by_path.keys()):
        errors.append(f"UNEXPECTED_FILE:{path}")
    for path in sorted(expected_by_path.keys() & actual_by_path.keys()):
        expected = expected_by_path[path]
        observed = actual_by_path[path]
        if expected.bytes_count != observed.bytes_count:
            errors.append(f"BYTE_COUNT_MISMATCH:{path}")
        if expected.sha256 != observed.sha256:
            errors.append(f"HASH_MISMATCH:{path}")
    content_root = canonical_sha256(tuple({"path": record.path, "bytes_count": record.bytes_count, "sha256": record.sha256} for record in actual))
    if content_root != manifest.content_root_sha256:
        errors.append("CONTENT_ROOT_MISMATCH")
    return BackupVerification(not errors, tuple(errors), len(actual), content_root)
