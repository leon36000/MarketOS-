"""Append-only point-in-time venue sessions.

This is a provider-neutral conformance calendar.  UTC nanosecond intervals are
stored explicitly; timezone conversion and exchange-vendor qualification remain
external gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable
from uuid import UUID

from .canonical import canonical_sha256
from .errors import DomainError, DuplicateConflict, InvariantViolation

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AmbiguousSession(DomainError):
    """Raised when multiple latest-known sessions cover one venue instant."""


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    HALTED = "HALTED"


def _time(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)
    return value


@dataclass(frozen=True, slots=True)
class SessionVersion:
    session_id: UUID
    version: int
    venue_id: UUID
    session_date: str
    label: str
    status: SessionStatus
    open_ns: int
    close_ns: int
    first_seen_at_ns: int
    available_to_strategy_at_ns: int
    revision_time_ns: int
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, UUID) or not isinstance(self.venue_id, UUID):
            raise InvariantViolation("INVALID_SESSION_IDENTITY")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_SESSION_VERSION")
        if not _DATE.fullmatch(self.session_date):
            raise InvariantViolation("INVALID_SESSION_DATE")
        label = self.label.strip().upper()
        if not label:
            raise InvariantViolation("MISSING_SESSION_LABEL")
        if not isinstance(self.status, SessionStatus):
            raise InvariantViolation("INVALID_SESSION_STATUS")
        _time(self.open_ns, "INVALID_SESSION_OPEN")
        _time(self.close_ns, "INVALID_SESSION_CLOSE")
        if self.close_ns <= self.open_ns:
            raise InvariantViolation("INVALID_SESSION_INTERVAL")
        _time(self.first_seen_at_ns, "INVALID_SESSION_FIRST_SEEN")
        _time(self.available_to_strategy_at_ns, "INVALID_SESSION_AVAILABLE")
        _time(self.revision_time_ns, "INVALID_SESSION_REVISION")
        if self.available_to_strategy_at_ns < self.first_seen_at_ns:
            raise InvariantViolation("SESSION_AVAILABLE_BEFORE_FIRST_SEEN")
        if self.revision_time_ns < self.first_seen_at_ns:
            raise InvariantViolation("SESSION_REVISION_BEFORE_FIRST_SEEN")
        source = self.source_id.strip()
        if not source:
            raise InvariantViolation("MISSING_SESSION_SOURCE")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "source_id", source)

    def covers(self, instant_ns: int) -> bool:
        _time(instant_ns, "INVALID_SESSION_INSTANT")
        return (
            self.status is SessionStatus.OPEN
            and self.open_ns <= instant_ns < self.close_ns
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "version": self.version,
            "venue_id": self.venue_id,
            "session_date": self.session_date,
            "label": self.label,
            "status": self.status,
            "open_ns": self.open_ns,
            "close_ns": self.close_ns,
            "first_seen_at_ns": self.first_seen_at_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "revision_time_ns": self.revision_time_ns,
            "source_id": self.source_id,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class VenueCalendar:
    """In-memory reference calendar with append-only revisions."""

    live_trading_state = "HARD_LOCKED"
    provider_selected = False

    def __init__(self) -> None:
        self._history: dict[UUID, list[SessionVersion]] = {}
        self._hashes: dict[tuple[UUID, int], str] = {}

    def append(self, session: SessionVersion) -> bool:
        key = (session.session_id, session.version)
        digest = session.sha256()
        existing = self._hashes.get(key)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(
                    f"SESSION_VERSION_CONFLICT:{session.session_id}:{session.version}"
                )
            return False
        history = self._history.setdefault(session.session_id, [])
        expected = len(history) + 1
        if session.version != expected:
            raise InvariantViolation(
                f"SESSION_VERSION_SEQUENCE:expected={expected}:actual={session.version}"
            )
        if history:
            previous = history[-1]
            identity = (session.venue_id, session.session_date, session.label)
            previous_identity = (
                previous.venue_id,
                previous.session_date,
                previous.label,
            )
            if identity != previous_identity:
                raise InvariantViolation("SESSION_IDENTITY_MUTATION")
            if session.revision_time_ns < previous.revision_time_ns:
                raise InvariantViolation("SESSION_REVISION_TIME_REGRESSION")
            if (
                session.available_to_strategy_at_ns
                < previous.available_to_strategy_at_ns
            ):
                raise InvariantViolation("SESSION_KNOWLEDGE_TIME_REGRESSION")
        history.append(session)
        self._hashes[key] = digest
        return True

    @staticmethod
    def _latest_known(
        records: Iterable[SessionVersion],
        *,
        knowledge_time_ns: int,
    ) -> SessionVersion | None:
        _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        known = [
            record
            for record in records
            if record.available_to_strategy_at_ns <= knowledge_time_ns
        ]
        if not known:
            return None
        return max(
            known,
            key=lambda record: (
                record.revision_time_ns,
                record.available_to_strategy_at_ns,
                record.version,
            ),
        )

    def latest_known(
        self,
        session_id: UUID,
        *,
        knowledge_time_ns: int,
    ) -> SessionVersion | None:
        return self._latest_known(
            self._history.get(session_id, ()),
            knowledge_time_ns=knowledge_time_ns,
        )

    def sessions_as_known(
        self,
        venue_id: UUID,
        *,
        knowledge_time_ns: int,
    ) -> tuple[SessionVersion, ...]:
        if not isinstance(venue_id, UUID):
            raise InvariantViolation("INVALID_VENUE_ID")
        latest: list[SessionVersion] = []
        for history in self._history.values():
            session = self._latest_known(
                history,
                knowledge_time_ns=knowledge_time_ns,
            )
            if session is not None and session.venue_id == venue_id:
                latest.append(session)
        return tuple(
            sorted(
                latest,
                key=lambda item: (
                    item.open_ns,
                    item.close_ns,
                    item.label,
                    str(item.session_id),
                ),
            )
        )

    def session_for_time(
        self,
        venue_id: UUID,
        instant_ns: int,
        *,
        knowledge_time_ns: int,
    ) -> SessionVersion | None:
        _time(instant_ns, "INVALID_SESSION_INSTANT")
        candidates = [
            session
            for session in self.sessions_as_known(
                venue_id,
                knowledge_time_ns=knowledge_time_ns,
            )
            if session.covers(instant_ns)
        ]
        if len(candidates) > 1:
            raise AmbiguousSession(
                f"AMBIGUOUS_SESSION:{venue_id}:{instant_ns}:{knowledge_time_ns}"
            )
        return candidates[0] if candidates else None

    def is_open(
        self,
        venue_id: UUID,
        instant_ns: int,
        *,
        knowledge_time_ns: int,
    ) -> bool:
        return (
            self.session_for_time(
                venue_id,
                instant_ns,
                knowledge_time_ns=knowledge_time_ns,
            )
            is not None
        )

    def next_open(
        self,
        venue_id: UUID,
        after_ns: int,
        *,
        knowledge_time_ns: int,
    ) -> int | None:
        _time(after_ns, "INVALID_SESSION_INSTANT")
        openings = [
            session.open_ns
            for session in self.sessions_as_known(
                venue_id,
                knowledge_time_ns=knowledge_time_ns,
            )
            if session.status is SessionStatus.OPEN and session.open_ns >= after_ns
        ]
        return min(openings) if openings else None

    def history(self, session_id: UUID) -> tuple[SessionVersion, ...]:
        return tuple(self._history.get(session_id, ()))
