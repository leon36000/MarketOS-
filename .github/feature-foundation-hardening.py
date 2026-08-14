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


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"expected {expected} patch sites in {path}, found {count}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


# Calendar dates must be real ISO dates, not only regex-shaped strings.
replace_once(
    "src/marketos/sessions.py",
    '''from dataclasses import dataclass
from enum import Enum
''',
    '''from dataclasses import dataclass
from datetime import date
from enum import Enum
''',
)
replace_once(
    "src/marketos/sessions.py",
    '''        if not _DATE.fullmatch(self.session_date):
            raise InvariantViolation("INVALID_SESSION_DATE")
        label = self.label.strip().upper()
''',
    '''        if not _DATE.fullmatch(self.session_date):
            raise InvariantViolation("INVALID_SESSION_DATE")
        try:
            session_date = date.fromisoformat(self.session_date).isoformat()
        except ValueError as exc:
            raise InvariantViolation("INVALID_SESSION_DATE") from exc
        label = self.label.strip().upper()
''',
)
replace_once(
    "src/marketos/sessions.py",
    '''        object.__setattr__(self, "label", label)
        object.__setattr__(self, "source_id", source)
''',
    '''        object.__setattr__(self, "session_date", session_date)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "source_id", source)
''',
)

# A semantic feature key may not silently select between independent point IDs.
replace_once(
    "src/marketos/features.py",
    '''class FeatureDerivationDenied(DomainError):
    """Raised when rights or point-in-time authority blocks materialization."""


def _time''',
    '''class FeatureDerivationDenied(DomainError):
    """Raised when rights or point-in-time authority blocks materialization."""


class AmbiguousFeaturePoint(DomainError):
    """Raised when independent points occupy one semantic feature key."""


def _time''',
)

# Every point carries both bar and calendar-session lineage.
replace_once(
    "src/marketos/features.py",
    '''    input_root_sha256: str
    input_bar_sha256: tuple[str, ...]
''',
    '''    input_root_sha256: str
    input_bar_sha256: tuple[str, ...]
    input_session_sha256: tuple[str, ...]
''',
)
replace_once(
    "src/marketos/features.py",
    '''        for digest in (
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
        object.__setattr__(self, "input_bar_sha256", bars)
''',
    '''        for digest in (
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
''',
)
replace_count(
    "src/marketos/features.py",
    '''            "input_bar_sha256": self.input_bar_sha256,
''',
    '''            "input_bar_sha256": self.input_bar_sha256,
            "input_session_sha256": self.input_session_sha256,
''',
    2,
)

# Calendar lookup returns the exact latest-known session revision used.
replace_once(
    "src/marketos/features.py",
    ''') -> tuple[bool, int]:
''',
    ''') -> tuple[bool, int, tuple[str, ...]]:
''',
)
replace_count(
    "src/marketos/features.py",
    '''        return False, 0
''',
    '''        return False, 0, ()
''',
    2,
)
replace_once(
    "src/marketos/features.py",
    '''    return (
        True,
        max(
            start_session.available_to_strategy_at_ns,
            end_session.available_to_strategy_at_ns,
        ),
    )
''',
    '''    session_sha256 = start_session.sha256()
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
''',
)
replace_once(
    "src/marketos/features.py",
    '''    eligible: list[tuple[TradeBar, int]] = []
''',
    '''    eligible: list[tuple[TradeBar, int, tuple[str, ...]]] = []
''',
)
replace_once(
    "src/marketos/features.py",
    '''        in_session, session_available = _bar_is_in_session(
            bar,
            calendar,
            knowledge_time_ns=knowledge_time_ns,
        )
        if in_session:
            eligible.append((bar, session_available))
''',
    '''        in_session, session_available, session_hashes = _bar_is_in_session(
            bar,
            calendar,
            knowledge_time_ns=knowledge_time_ns,
        )
        if in_session:
            eligible.append((bar, session_available, session_hashes))
''',
)
replace_once(
    "src/marketos/features.py",
    '''    grouped: dict[tuple[UUID, UUID], list[tuple[TradeBar, int]]] = {}
''',
    '''    grouped: dict[
        tuple[UUID, UUID],
        list[tuple[TradeBar, int, tuple[str, ...]]],
    ] = {}
''',
)
replace_once(
    "src/marketos/features.py",
    '''            bar_hashes = tuple(item[0].sha256() for item in window)
            input_root = canonical_sha256(bar_hashes)
            available = max(
                max(item[0].available_to_strategy_at_ns for item in window),
                max(item[1] for item in window),
            )
            point_id = canonical_sha256(
                {
                    "feature_id": definition.feature_id,
                    "feature_version": definition.version,
                    "listing_id": listing_id,
                    "economic_time_ns": current_bar.interval_end_ns,
                }
            )
''',
    '''            bar_hashes = tuple(item[0].sha256() for item in window)
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
''',
)
replace_once(
    "src/marketos/features.py",
    '''                    definition_sha256=definition.sha256(),
                    rights_policy_sha256=rights_sha,
                    input_root_sha256=input_root,
                    input_bar_sha256=bar_hashes,
''',
    '''                    definition_sha256=definition_sha256,
                    rights_policy_sha256=rights_sha,
                    input_root_sha256=input_root,
                    input_bar_sha256=bar_hashes,
                    input_session_sha256=session_hashes,
''',
)

# Store the calendar lineage and verify existing rows before idempotent return.
replace_once(
    "src/marketos/features.py",
    '''                input_root_sha256 TEXT NOT NULL,
                input_bar_sha256_json TEXT NOT NULL,
                point_sha256 TEXT NOT NULL,
''',
    '''                input_root_sha256 TEXT NOT NULL,
                input_bar_sha256_json TEXT NOT NULL,
                input_session_sha256_json TEXT NOT NULL,
                point_sha256 TEXT NOT NULL,
''',
)
replace_once(
    "src/marketos/features.py",
    '''            bars_value = json.loads(row["input_bar_sha256_json"])
            if not isinstance(bars_value, list):
                raise ValueError("invalid input bars")
            point = FeaturePoint(
''',
    '''            bars_value = json.loads(row["input_bar_sha256_json"])
            sessions_value = json.loads(row["input_session_sha256_json"])
            if not isinstance(bars_value, list):
                raise ValueError("invalid input bars")
            if not isinstance(sessions_value, list):
                raise ValueError("invalid input sessions")
            point = FeaturePoint(
''',
)
replace_once(
    "src/marketos/features.py",
    '''                input_bar_sha256=tuple(str(item) for item in bars_value),
            )
''',
    '''                input_bar_sha256=tuple(str(item) for item in bars_value),
                input_session_sha256=tuple(
                    str(item) for item in sessions_value
                ),
            )
''',
)
replace_once(
    "src/marketos/features.py",
    '''            existing = self._connection.execute(
                "SELECT point_sha256 FROM feature_points WHERE point_id = ? AND version = ?",
                (point.point_id, point.version),
            ).fetchone()
            if existing is not None:
                if str(existing["point_sha256"]) != digest:
                    raise DuplicateConflict(
                        f"FEATURE_POINT_VERSION_CONFLICT:{point.point_id}:{point.version}"
                    )
                self._connection.execute("COMMIT")
                return False
''',
    '''            existing = self._connection.execute(
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
''',
)
replace_once(
    "src/marketos/features.py",
    '''                    definition_sha256, rights_policy_sha256, input_root_sha256,
                    input_bar_sha256_json, point_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''',
    '''                    definition_sha256, rights_policy_sha256, input_root_sha256,
                    input_bar_sha256_json, input_session_sha256_json,
                    point_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''',
)
replace_once(
    "src/marketos/features.py",
    '''                    json.dumps(point.input_bar_sha256, separators=(",", ":")),
                    digest,
''',
    '''                    json.dumps(point.input_bar_sha256, separators=(",", ":")),
                    json.dumps(
                        point.input_session_sha256,
                        separators=(",", ":"),
                    ),
                    digest,
''',
)

# Exact feature version is a mandatory query dimension; ambiguity is explicit.
replace_once(
    "src/marketos/features.py",
    '''        feature_id: str,
        listing_id: UUID,
''',
    '''        feature_id: str,
        feature_version: int,
        listing_id: UUID,
''',
)
replace_once(
    "src/marketos/features.py",
    '''        row = self._connection.execute(
            """
            SELECT * FROM feature_points
            WHERE feature_id = ?
              AND listing_id = ?
              AND economic_time_ns = ?
              AND available_to_strategy_at_ns <= ?
            ORDER BY feature_version DESC,
                     available_to_strategy_at_ns DESC,
                     version DESC
            LIMIT 1
            """,
            (
                feature_id,
                str(listing_id),
                economic_time_ns,
                knowledge_time_ns,
            ),
        ).fetchone()
        return None if row is None else self._from_row(row)
''',
    '''        if (
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
''',
)

# Existing tests and verifier now use a canonical bar+session input root.
for path in ("tests/test_features.py", "tools/verify_feature_foundation.py"):
    replace_once(
        path,
        '''from marketos.bars import TradeBar
''',
        '''from marketos.bars import TradeBar
from marketos.canonical import canonical_sha256
''',
    )
    replace_once(
        path,
        '''SESSION_ID = UUID("00000000-0000-0000-0000-000000008200")
'''
        if path.startswith("tests/")
        else '''SESSION_ID = UUID("00000000-0000-0000-0000-000000009200")
''',
        ('''SESSION_ID = UUID("00000000-0000-0000-0000-000000008200")
INPUT_BARS = ("1" * 64, "2" * 64)
INPUT_SESSIONS = ("3" * 64,)
INPUT_ROOT = canonical_sha256(
    {"bars": INPUT_BARS, "sessions": INPUT_SESSIONS}
)
'''
        if path.startswith("tests/")
        else '''SESSION_ID = UUID("00000000-0000-0000-0000-000000009200")
INPUT_BARS = ("1" * 64, "2" * 64)
INPUT_SESSIONS = ("3" * 64,)
INPUT_ROOT = canonical_sha256(
    {"bars": INPUT_BARS, "sessions": INPUT_SESSIONS}
)
'''),
    )
    replace_count(
        path,
        '''input_root_sha256="c" * 64,
''',
        '''input_root_sha256=INPUT_ROOT,
''',
        2 if path.startswith("tests/") else 3,
    )
    replace_count(
        path,
        '''input_bar_sha256=("1" * 64, "2" * 64),
''',
        '''input_bar_sha256=INPUT_BARS,
                input_session_sha256=INPUT_SESSIONS,
''',
        2 if path.startswith("tests/") else 3,
    )

replace_count(
    "tests/test_features.py",
    '''store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=''',
    '''store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=''',
    4,
)
replace_count(
    "tools/verify_feature_foundation.py",
    '''store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=''',
    '''store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=''',
    4,
)

# Permanent documentation describes the stronger lineage and query contract.
replace_once(
    "docs/implementation/MARKET_CALENDAR_FEATURE_STORE.md",
    '''- input-bar, definition and rights lineage in every point;
- availability equal to the latest bar or session revision used;
''',
    '''- input-bar, calendar-session, definition and rights lineage in every point;
- a canonical root that must match both bar and session input hashes;
- availability equal to the latest bar or session revision used;
''',
)
replace_once(
    "docs/implementation/MARKET_CALENDAR_FEATURE_STORE.md",
    '''- append-only SQLite feature revisions with latest-known queries;
- stored feature hash verification and idempotent duplicate handling;
''',
    '''- append-only SQLite feature revisions with exact-version latest-known queries;
- explicit ambiguity when independent points occupy one semantic feature key;
- stored feature hash verification before idempotent duplicate handling;
''',
)
