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


# Complete calendar-session lineage propagation from the partially patched
# source.  The first no-session branch already returns the three-field tuple.
replace_once(
    "src/marketos/features.py",
    '''    if start_session.session_id != end_session.session_id:
        return False, 0
    return (
        True,
        max(
            start_session.available_to_strategy_at_ns,
            end_session.available_to_strategy_at_ns,
        ),
    )
''',
    '''    if start_session.session_id != end_session.session_id:
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

# Persist the session lineage and verify stored content before returning an
# idempotent duplicate response.
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

# Querying a feature requires the exact feature version.  Independent point IDs
# for one semantic key are an explicit error, never an arbitrary LIMIT 1.
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

# Existing tests and the independent verifier now construct a canonical
# bar+session lineage root and pin feature version on reads.
for path, session_id in (
    (
        "tests/test_features.py",
        "00000000-0000-0000-0000-000000008200",
    ),
    (
        "tools/verify_feature_foundation.py",
        "00000000-0000-0000-0000-000000009200",
    ),
):
    replace_once(
        path,
        '''from marketos.bars import TradeBar
''',
        '''from marketos.bars import TradeBar
from marketos.canonical import canonical_sha256
''',
    )
    marker = f'SESSION_ID = UUID("{session_id}")\n'
    replacement = marker + '''INPUT_BARS = ("1" * 64, "2" * 64)
INPUT_SESSIONS = ("3" * 64,)
INPUT_ROOT = canonical_sha256(
    {"bars": INPUT_BARS, "sessions": INPUT_SESSIONS}
)
'''
    replace_once(path, marker, replacement)
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
        path,
        '''store.as_of("close-return", LISTING_ID, 2_000, knowledge_time_ns=''',
        '''store.as_of("close-return", 1, LISTING_ID, 2_000, knowledge_time_ns=''',
        4,
    )

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
