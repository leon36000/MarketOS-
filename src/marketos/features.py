"""Point-in-time feature definitions, materialization and append-only store."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable
from uuid import UUID

from .bars import TradeBar
from .canonical import canonical_json, canonical_sha256
from .errors import DomainError, DuplicateConflict, InvariantViolation
from .rights import RightsPolicy
from .sessions import VenueCalendar

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class FeatureDerivationDenied(DomainError):
    """Raised when rights or point-in-time authority blocks materialization."""


class AmbiguousFeaturePoint(DomainError):
    """Raised when independent points occupy one semantic feature key."""


def _time(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


def _decimal(value: Decimal, code: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(code)
    return value


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    feature_id: str
    version: int
    family: str
    lookback: int
    output_scale: int
    code_sha256: str
    config_sha256: str
    input_schema_ids: tuple[str, ...]
    rights_policy_ids: tuple[str, ...]
    null_policy: str

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.feature_id):
            raise InvariantViolation("INVALID_FEATURE_ID")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_FEATURE_VERSION")
        family = self.family.strip().upper()
        if not family:
            raise InvariantViolation("MISSING_FEATURE_FAMILY")
        if isinstance(self.lookback, bool) or not isinstance(self.lookback, int) or self.lookback < 1:
            raise InvariantViolation("INVALID_FEATURE_LOOKBACK")
        if isinstance(self.output_scale, bool) or not isinstance(self.output_scale, int) or not 0 <= self.output_scale <= 18:
            raise InvariantViolation("INVALID_FEATURE_OUTPUT_SCALE")
        for digest in (self.code_sha256, self.config_sha256):
            if not _HEX64.fullmatch(digest):
                raise InvariantViolation("INVALID_FEATURE_DEPENDENCY_SHA256")
        if not self.input_schema_ids or any(
            not isinstance(item, str) or not item.strip()
            for item in self.input_schema_ids
        ):
            raise InvariantViolation("MISSING_FEATURE_INPUT_SCHEMA")
        if len(self.input_schema_ids) != len(set(self.input_schema_ids)):
            raise InvariantViolation("DUPLICATE_FEATURE_INPUT_SCHEMA")
        if not self.rights_policy_ids or any(
            not isinstance(item, str) or not item.strip()
            for item in self.rights_policy_ids
        ):
            raise InvariantViolation("MISSING_FEATURE_RIGHTS_POLICY")
        if len(self.rights_policy_ids) != len(set(self.rights_policy_ids)):
            raise InvariantViolation("DUPLICATE_FEATURE_RIGHTS_POLICY")
        if self.null_policy not in {"SKIP", "ERROR"}:
            raise InvariantViolation("INVALID_FEATURE_NULL_POLICY")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "input_schema_ids", tuple(self.input_schema_ids))
        object.__setattr__(self, "rights_policy_ids", tuple(sorted(self.rights_policy_ids)))

    def canonical_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "version": self.version,
            "family": self.family,
            "lookback": self.lookback,
            "output_scale": self.output_scale,
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
            "input_schema_ids": self.input_schema_ids,
            "rights_policy_ids": self.rights_policy_ids,
            "null_policy": self.null_policy,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class FeaturePoint:
    point_id: str
    version: int
    feature_id: str
    feature_version: int
    listing_id: UUID
    economic_time_ns: int
    available_to_strategy_at_ns: int
    value: Decimal
    definition_sha256: str
    rights_policy_sha256: str
    input_root_sha256: str
    input_bar_sha256: tuple[str, ...]
    input_session_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.point_id.strip():
            raise InvariantViolation("MISSING_FEATURE_POINT_ID")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_FEATURE_POINT_VERSION")
        if not _SAFE_ID.fullmatch(self.feature_id):
            raise InvariantViolation("INVALID_FEATURE_ID")
        if isinstance(self.feature_version, bool) or not isinstance(self.feature_version, int) or self.feature_version < 1:
            raise InvariantViolation("INVALID_FEATURE_VERSION")
        if not isinstance(self.listing_id, UUID):
            raise InvariantViolation("INVALID_FEATURE_LISTING_ID")
        _time(self.economic_time_ns, "INVALID_FEATURE_ECONOMIC_TIME")
        _time(self.available_to_strategy_at_ns, "INVALID_FEATURE_AVAILABLE_TIME")
        if self.available_to_strategy_at_ns < self.economic_time_ns:
            raise InvariantViolation("FEATURE_AVAILABLE_BEFORE_ECONOMIC_TIME")
        object.__setattr__(self, "value", _decimal(self.value, "INVALID_FEATURE_VALUE"))
        for digest in (
            self.definition_sha256,
            self.rights_policy_sha256,
            self.input_root_sha256,
        ):
            if not _HEX64.fullmatch(digest):
                raise InvariantViolation("INVALID_FEATURE_SHA256")
        bars = tuple(self.input_bar_sha256)
        if not bars or any(not _HEX64.fullmatch(digest) for digest in bars):
            raise InvariantViolation("INVALID_FEATURE_INPUT_BAR_SHA256")
        if len(bars) != len(set(bars)):
            raise InvariantViolation("DUPLICATE_FEATURE_INPUT_BAR")
        sessions = tuple(self.input_session_sha256)
        if not sessions or any(not _HEX64.fullmatch(digest) for digest in sessions):
            raise InvariantViolation("INVALID_FEATURE_INPUT_SESSION_SHA256")
        if len(sessions) != len(set(sessions)):
            raise InvariantViolation("DUPLICATE_FEATURE_INPUT_SESSION")
        expected_root = canonical_sha256(
            {"bars": bars, "sessions": sessions}
        )
        if self.input_root_sha256 != expected_root:
            raise InvariantViolation("FEATURE_INPUT_ROOT_MISMATCH")
        object.__setattr__(self, "input_bar_sha256", bars)
        object.__setattr__(self, "input_session_sha256", sessions)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "point_id": self.point_id,
            "version": self.version,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "listing_id": self.listing_id,
            "economic_time_ns": self.economic_time_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "value": self.value,
            "definition_sha256": self.definition_sha256,
            "rights_policy_sha256": self.rights_policy_sha256,
            "input_root_sha256": self.input_root_sha256,
            "input_bar_sha256": self.input_bar_sha256,
            "input_session_sha256": self.input_session_sha256,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())

    def as_kwargs(self) -> dict[str, object]:
        return {
            "point_id": self.point_id,
            "version": self.version,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "listing_id": self.listing_id,
            "economic_time_ns": self.economic_time_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "value": self.value,
            "definition_sha256": self.definition_sha256,
            "rights_policy_sha256": self.rights_policy_sha256,
            "input_root_sha256": self.input_root_sha256,
            "input_bar_sha256": self.input_bar_sha256,
            "input_session_sha256": self.input_session_sha256,
        }


def _admit_rights(
    definition: FeatureDefinition,
    rights_policy: RightsPolicy,
) -> str:
    for capability in ("non_display", "historical_replay", "derived_data"):
        if not rights_policy.allows(capability):
            raise FeatureDerivationDenied(
                f"FEATURE_DERIVATION_RIGHT_DENIED:{rights_policy.policy_id}:{capability}"
            )
    if set(definition.rights_policy_ids) != {rights_policy.policy_id}:
        raise FeatureDerivationDenied(
            f"FEATURE_DEFINITION_RIGHTS_MISMATCH:{definition.feature_id}:{rights_policy.policy_id}"
        )
    return rights_policy.sha256()


def _bar_is_in_session(
    bar: TradeBar,
    calendar: VenueCalendar,
    *,
    knowledge_time_ns: int,
) -> tuple[bool, int, tuple[str, ...]]:
    if bar.interval_end_ns <= bar.interval_start_ns:
        raise InvariantViolation("INVALID_BAR_INTERVAL")
    start_session = calendar.session_for_time(
        bar.venue_id,
        bar.interval_start_ns,
        knowledge_time_ns=knowledge_time_ns,
    )
    end_session = calendar.session_for_time(
        bar.venue_id,
        bar.interval_end_ns - 1,
        knowledge_time_ns=knowledge_time_ns,
    )
    if start_session is None or end_session is None:
        return False, 0, ()
    if start_session.session_id != end_session.session_id:
        return False, 0, ()
    session_sha256 = start_session.sha256()
    if session_sha256 != end_session.sha256():
        raise InvariantViolation("FEATURE_SESSION_REVISION_MISMATCH")
    return (
        True,
        max(
            start_session.available_to_strategy_at_ns,
            end_session.available_to_strategy_at_ns,
        ),
        (session_sha256,),
    )


def build_close_return_features(
    bars: Iterable[TradeBar],
    *,
    definition: FeatureDefinition,
    rights_policy: RightsPolicy,
    calendar: VenueCalendar,
    knowledge_time_ns: int,
) -> tuple[FeaturePoint, ...]:
    """Build quantized close-to-close returns as known at a cutoff."""

    _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
    rights_sha = _admit_rights(definition, rights_policy)
    seen: set[tuple[UUID, UUID, int, int]] = set()
    eligible: list[tuple[TradeBar, int, tuple[str, ...]]] = []
    for bar in bars:
        identity = (
            bar.listing_id,
            bar.venue_id,
            bar.interval_start_ns,
            bar.interval_end_ns,
        )
        if identity in seen:
            raise InvariantViolation(
                f"DUPLICATE_FEATURE_INPUT_BAR:{bar.listing_id}:{bar.interval_start_ns}:{bar.interval_end_ns}"
            )
        seen.add(identity)
        if bar.rights_policy_sha256 != rights_sha:
            raise FeatureDerivationDenied(
                f"FEATURE_INPUT_RIGHTS_MISMATCH:{bar.listing_id}:{bar.interval_end_ns}"
            )
        if bar.available_to_strategy_at_ns > knowledge_time_ns:
            continue
        in_session, session_available, session_hashes = _bar_is_in_session(
            bar,
            calendar,
            knowledge_time_ns=knowledge_time_ns,
        )
        if in_session:
            eligible.append((bar, session_available, session_hashes))

    eligible.sort(
        key=lambda item: (
            str(item[0].listing_id),
            str(item[0].venue_id),
            item[0].interval_end_ns,
            item[0].input_root_sha256,
        )
    )
    grouped: dict[
        tuple[UUID, UUID],
        list[tuple[TradeBar, int, tuple[str, ...]]],
    ] = {}
    for item in eligible:
        grouped.setdefault((item[0].listing_id, item[0].venue_id), []).append(item)

    quantizer = Decimal(1).scaleb(-definition.output_scale)
    points: list[FeaturePoint] = []
    for (listing_id, _venue_id), group in sorted(
        grouped.items(),
        key=lambda item: (str(item[0][0]), str(item[0][1])),
    ):
        for index in range(definition.lookback, len(group)):
            window = group[index - definition.lookback : index + 1]
            first_bar = window[0][0]
            current_bar = window[-1][0]
            if any(
                left[0].interval_end_ns != right[0].interval_start_ns
                for left, right in zip(window, window[1:])
            ):
                if definition.null_policy == "ERROR":
                    raise InvariantViolation(
                        f"FEATURE_INPUT_GAP:{definition.feature_id}:{listing_id}:{current_bar.interval_end_ns}"
                    )
                continue
            if first_bar.close.value == 0:
                if definition.null_policy == "ERROR":
                    raise InvariantViolation(
                        f"FEATURE_ZERO_DENOMINATOR:{definition.feature_id}:{listing_id}:{current_bar.interval_end_ns}"
                    )
                continue
            raw_value = current_bar.close.value / first_bar.close.value - Decimal("1")
            value = raw_value.quantize(quantizer, rounding=ROUND_HALF_EVEN)
            bar_hashes = tuple(item[0].sha256() for item in window)
            session_hashes = tuple(
                sorted(
                    {
                        digest
                        for item in window
                        for digest in item[2]
                    }
                )
            )
            input_root = canonical_sha256(
                {"bars": bar_hashes, "sessions": session_hashes}
            )
            available = max(
                max(item[0].available_to_strategy_at_ns for item in window),
                max(item[1] for item in window),
            )
            definition_sha256 = definition.sha256()
            point_id = canonical_sha256(
                {
                    "feature_id": definition.feature_id,
                    "feature_version": definition.version,
                    "listing_id": listing_id,
                    "economic_time_ns": current_bar.interval_end_ns,
                    "definition_sha256": definition_sha256,
                    "rights_policy_sha256": rights_sha,
                }
            )
            points.append(
                FeaturePoint(
                    point_id=point_id,
                    version=1,
                    feature_id=definition.feature_id,
                    feature_version=definition.version,
                    listing_id=listing_id,
                    economic_time_ns=current_bar.interval_end_ns,
                    available_to_strategy_at_ns=available,
                    value=value,
                    definition_sha256=definition_sha256,
                    rights_policy_sha256=rights_sha,
                    input_root_sha256=input_root,
                    input_bar_sha256=bar_hashes,
                    input_session_sha256=session_hashes,
                )
            )
    return tuple(points)


class FeatureStore:
    """SQLite append-only point store with latest-known revisions."""

    live_trading_state = "HARD_LOCKED"
    backend_selected = False
    feature_edge_proven = False

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS feature_points (
                point_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                feature_id TEXT NOT NULL,
                feature_version INTEGER NOT NULL,
                listing_id TEXT NOT NULL,
                economic_time_ns INTEGER NOT NULL,
                available_to_strategy_at_ns INTEGER NOT NULL,
                value_text TEXT NOT NULL,
                definition_sha256 TEXT NOT NULL,
                rights_policy_sha256 TEXT NOT NULL,
                input_root_sha256 TEXT NOT NULL,
                input_bar_sha256_json TEXT NOT NULL,
                input_session_sha256_json TEXT NOT NULL,
                point_sha256 TEXT NOT NULL,
                PRIMARY KEY(point_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_feature_point_asof
              ON feature_points(
                feature_id, listing_id, economic_time_ns,
                available_to_strategy_at_ns, feature_version, version
              );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "FeatureStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FeaturePoint:
        try:
            bars_value = json.loads(row["input_bar_sha256_json"])
            sessions_value = json.loads(row["input_session_sha256_json"])
            if not isinstance(bars_value, list):
                raise ValueError("invalid input bars")
            if not isinstance(sessions_value, list):
                raise ValueError("invalid input sessions")
            point = FeaturePoint(
                point_id=str(row["point_id"]),
                version=int(row["version"]),
                feature_id=str(row["feature_id"]),
                feature_version=int(row["feature_version"]),
                listing_id=UUID(str(row["listing_id"])),
                economic_time_ns=int(row["economic_time_ns"]),
                available_to_strategy_at_ns=int(row["available_to_strategy_at_ns"]),
                value=Decimal(str(row["value_text"])),
                definition_sha256=str(row["definition_sha256"]),
                rights_policy_sha256=str(row["rights_policy_sha256"]),
                input_root_sha256=str(row["input_root_sha256"]),
                input_bar_sha256=tuple(str(item) for item in bars_value),
                input_session_sha256=tuple(
                    str(item) for item in sessions_value
                ),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise InvariantViolation(
                f"FEATURE_POINT_HASH_MISMATCH:{row['point_id']}:{row['version']}"
            ) from exc
        if point.sha256() != str(row["point_sha256"]):
            raise InvariantViolation(
                f"FEATURE_POINT_HASH_MISMATCH:{point.point_id}:{point.version}"
            )
        return point

    def append(self, point: FeaturePoint) -> bool:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            digest = point.sha256()
            existing = self._connection.execute(
                "SELECT * FROM feature_points WHERE point_id = ? AND version = ?",
                (point.point_id, point.version),
            ).fetchone()
            if existing is not None:
                stored = self._from_row(existing)
                if stored.sha256() != digest:
                    raise DuplicateConflict(
                        f"FEATURE_POINT_VERSION_CONFLICT:{point.point_id}:{point.version}"
                    )
                self._connection.execute("COMMIT")
                return False
            latest = self._connection.execute(
                "SELECT * FROM feature_points WHERE point_id = ? ORDER BY version DESC LIMIT 1",
                (point.point_id,),
            ).fetchone()
            expected = 1 if latest is None else int(latest["version"]) + 1
            if point.version != expected:
                raise InvariantViolation(
                    f"FEATURE_POINT_VERSION_SEQUENCE:expected={expected}:actual={point.version}"
                )
            if latest is not None:
                identity = (
                    point.feature_id,
                    point.feature_version,
                    str(point.listing_id),
                    point.economic_time_ns,
                    point.definition_sha256,
                    point.rights_policy_sha256,
                )
                previous_identity = (
                    str(latest["feature_id"]),
                    int(latest["feature_version"]),
                    str(latest["listing_id"]),
                    int(latest["economic_time_ns"]),
                    str(latest["definition_sha256"]),
                    str(latest["rights_policy_sha256"]),
                )
                if identity != previous_identity:
                    raise InvariantViolation("FEATURE_POINT_IDENTITY_MUTATION")
                if point.available_to_strategy_at_ns < int(
                    latest["available_to_strategy_at_ns"]
                ):
                    raise InvariantViolation("FEATURE_POINT_KNOWLEDGE_TIME_REGRESSION")
            self._connection.execute(
                """
                INSERT INTO feature_points(
                    point_id, version, feature_id, feature_version, listing_id,
                    economic_time_ns, available_to_strategy_at_ns, value_text,
                    definition_sha256, rights_policy_sha256, input_root_sha256,
                    input_bar_sha256_json, input_session_sha256_json,
                    point_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.point_id,
                    point.version,
                    point.feature_id,
                    point.feature_version,
                    str(point.listing_id),
                    point.economic_time_ns,
                    point.available_to_strategy_at_ns,
                    format(point.value, "f"),
                    point.definition_sha256,
                    point.rights_policy_sha256,
                    point.input_root_sha256,
                    json.dumps(point.input_bar_sha256, separators=(",", ":")),
                    json.dumps(
                        point.input_session_sha256,
                        separators=(",", ":"),
                    ),
                    digest,
                ),
            )
            self._connection.execute("COMMIT")
            return True
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def history(self, point_id: str) -> tuple[FeaturePoint, ...]:
        rows = self._connection.execute(
            "SELECT * FROM feature_points WHERE point_id = ? ORDER BY version",
            (point_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def as_of(
        self,
        feature_id: str,
        feature_version: int,
        listing_id: UUID,
        economic_time_ns: int,
        *,
        knowledge_time_ns: int,
    ) -> FeaturePoint | None:
        _time(economic_time_ns, "INVALID_FEATURE_ECONOMIC_TIME")
        _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        if (
            isinstance(feature_version, bool)
            or not isinstance(feature_version, int)
            or feature_version < 1
        ):
            raise InvariantViolation("INVALID_FEATURE_VERSION")
        rows = self._connection.execute(
            """
            SELECT * FROM feature_points
            WHERE feature_id = ?
              AND feature_version = ?
              AND listing_id = ?
              AND economic_time_ns = ?
              AND available_to_strategy_at_ns <= ?
            ORDER BY point_id,
                     available_to_strategy_at_ns DESC,
                     version DESC
            """,
            (
                feature_id,
                feature_version,
                str(listing_id),
                economic_time_ns,
                knowledge_time_ns,
            ),
        ).fetchall()
        latest_by_point_id: dict[str, FeaturePoint] = {}
        for row in rows:
            point_id = str(row["point_id"])
            if point_id not in latest_by_point_id:
                latest_by_point_id[point_id] = self._from_row(row)
        if len(latest_by_point_id) > 1:
            raise AmbiguousFeaturePoint(
                f"AMBIGUOUS_FEATURE_POINT:{feature_id}:{feature_version}:"
                f"{listing_id}:{economic_time_ns}:{knowledge_time_ns}"
            )
        return next(iter(latest_by_point_id.values()), None)
