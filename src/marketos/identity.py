"""Bitemporal Security Master with UUID primary identity.

Symbols and external identifiers are versioned aliases.  Records are append-only
and historical/delisted listings remain queryable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable
from uuid import UUID

from .canonical import canonical_sha256
from .errors import DomainError, DuplicateConflict, InvariantViolation


class AmbiguousIdentity(DomainError):
    """Raised when a point-in-time alias resolves to multiple entities."""


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class IdentifierType(str, Enum):
    MARKETOS_ID = "MARKETOS_ID"
    FIGI = "FIGI"
    COMPOSITE_FIGI = "COMPOSITE_FIGI"
    SHARE_CLASS_FIGI = "SHARE_CLASS_FIGI"
    ISIN = "ISIN"
    CUSIP = "CUSIP"
    SEDOL = "SEDOL"
    CIK = "CIK"
    LEI = "LEI"
    CFI = "CFI"
    FISN = "FISN"
    MIC = "MIC"
    LOCAL_SYMBOL = "LOCAL_SYMBOL"
    VENDOR_SYMBOL = "VENDOR_SYMBOL"


def _uuid(value: UUID, code: str) -> None:
    if not isinstance(value, UUID):
        raise InvariantViolation(code)


def _time(value: int, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvariantViolation(code)


def _interval(valid_from_ns: int, valid_to_ns: int | None) -> None:
    _time(valid_from_ns, "INVALID_VALID_FROM")
    if valid_to_ns is not None:
        _time(valid_to_ns, "INVALID_VALID_TO")
        if valid_to_ns <= valid_from_ns:
            raise InvariantViolation("INVALID_VALID_INTERVAL")


def _contains(valid_from_ns: int, valid_to_ns: int | None, value: int) -> bool:
    return valid_from_ns <= value and (valid_to_ns is None or value < valid_to_ns)


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: UUID
    asset_class: str
    currency: str

    def __post_init__(self) -> None:
        _uuid(self.instrument_id, "INVALID_INSTRUMENT_ID")
        if not self.asset_class.strip():
            raise InvariantViolation("MISSING_ASSET_CLASS")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise InvariantViolation("INVALID_INSTRUMENT_CURRENCY")
        object.__setattr__(self, "asset_class", self.asset_class.upper())
        object.__setattr__(self, "currency", self.currency.upper())

    def canonical_dict(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "asset_class": self.asset_class,
            "currency": self.currency,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class Venue:
    venue_id: UUID
    mic: str
    name: str

    def __post_init__(self) -> None:
        _uuid(self.venue_id, "INVALID_VENUE_ID")
        mic = self.mic.upper()
        if len(mic) != 4 or not mic.isalnum():
            raise InvariantViolation("INVALID_MIC")
        if not self.name.strip():
            raise InvariantViolation("MISSING_VENUE_NAME")
        object.__setattr__(self, "mic", mic)

    def canonical_dict(self) -> dict[str, object]:
        return {"venue_id": self.venue_id, "mic": self.mic, "name": self.name}

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ListingVersion:
    listing_id: UUID
    version: int
    instrument_id: UUID
    venue_id: UUID
    symbol: str
    status: ListingStatus
    valid_from_ns: int
    valid_to_ns: int | None
    first_seen_at_ns: int
    available_to_strategy_at_ns: int
    revision_time_ns: int

    def __post_init__(self) -> None:
        _uuid(self.listing_id, "INVALID_LISTING_ID")
        _uuid(self.instrument_id, "INVALID_INSTRUMENT_ID")
        _uuid(self.venue_id, "INVALID_VENUE_ID")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_LISTING_VERSION")
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise InvariantViolation("MISSING_LISTING_SYMBOL")
        if not isinstance(self.status, ListingStatus):
            raise InvariantViolation("INVALID_LISTING_STATUS")
        _interval(self.valid_from_ns, self.valid_to_ns)
        for value, code in (
            (self.first_seen_at_ns, "INVALID_FIRST_SEEN_TIME"),
            (self.available_to_strategy_at_ns, "INVALID_AVAILABLE_TIME"),
            (self.revision_time_ns, "INVALID_REVISION_TIME"),
        ):
            _time(value, code)
        if self.available_to_strategy_at_ns < self.first_seen_at_ns:
            raise InvariantViolation("AVAILABLE_BEFORE_FIRST_SEEN")
        if self.revision_time_ns < self.first_seen_at_ns:
            raise InvariantViolation("REVISION_BEFORE_FIRST_SEEN")
        object.__setattr__(self, "symbol", symbol)

    def visible(self, *, economic_time_ns: int, knowledge_time_ns: int) -> bool:
        return (
            _contains(self.valid_from_ns, self.valid_to_ns, economic_time_ns)
            and self.available_to_strategy_at_ns <= knowledge_time_ns
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "listing_id": self.listing_id,
            "version": self.version,
            "instrument_id": self.instrument_id,
            "venue_id": self.venue_id,
            "symbol": self.symbol,
            "status": self.status,
            "valid_from_ns": self.valid_from_ns,
            "valid_to_ns": self.valid_to_ns,
            "first_seen_at_ns": self.first_seen_at_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "revision_time_ns": self.revision_time_ns,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class IdentifierAssignment:
    assignment_id: UUID
    version: int
    entity_id: UUID
    identifier_type: IdentifierType
    value: str
    valid_from_ns: int
    valid_to_ns: int | None
    first_seen_at_ns: int
    available_to_strategy_at_ns: int
    revision_time_ns: int

    def __post_init__(self) -> None:
        _uuid(self.assignment_id, "INVALID_ASSIGNMENT_ID")
        _uuid(self.entity_id, "INVALID_IDENTIFIER_ENTITY")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvariantViolation("INVALID_IDENTIFIER_VERSION")
        if not isinstance(self.identifier_type, IdentifierType):
            raise InvariantViolation("INVALID_IDENTIFIER_TYPE")
        value = self.value.strip().upper()
        if not value:
            raise InvariantViolation("MISSING_IDENTIFIER_VALUE")
        _interval(self.valid_from_ns, self.valid_to_ns)
        for item, code in (
            (self.first_seen_at_ns, "INVALID_FIRST_SEEN_TIME"),
            (self.available_to_strategy_at_ns, "INVALID_AVAILABLE_TIME"),
            (self.revision_time_ns, "INVALID_REVISION_TIME"),
        ):
            _time(item, code)
        if self.available_to_strategy_at_ns < self.first_seen_at_ns:
            raise InvariantViolation("AVAILABLE_BEFORE_FIRST_SEEN")
        object.__setattr__(self, "value", value)

    def visible(self, *, economic_time_ns: int, knowledge_time_ns: int) -> bool:
        return (
            _contains(self.valid_from_ns, self.valid_to_ns, economic_time_ns)
            and self.available_to_strategy_at_ns <= knowledge_time_ns
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "version": self.version,
            "entity_id": self.entity_id,
            "identifier_type": self.identifier_type,
            "value": self.value,
            "valid_from_ns": self.valid_from_ns,
            "valid_to_ns": self.valid_to_ns,
            "first_seen_at_ns": self.first_seen_at_ns,
            "available_to_strategy_at_ns": self.available_to_strategy_at_ns,
            "revision_time_ns": self.revision_time_ns,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class SecurityMaster:
    """In-memory reference implementation of append-only bitemporal identity."""

    live_trading_state = "HARD_LOCKED"

    def __init__(self) -> None:
        self._instruments: dict[UUID, Instrument] = {}
        self._instrument_hashes: dict[UUID, str] = {}
        self._venues: dict[UUID, Venue] = {}
        self._venue_by_mic: dict[str, UUID] = {}
        self._venue_hashes: dict[UUID, str] = {}
        self._listings: dict[UUID, list[ListingVersion]] = {}
        self._listing_hashes: dict[tuple[UUID, int], str] = {}
        self._identifiers: dict[UUID, list[IdentifierAssignment]] = {}
        self._identifier_hashes: dict[tuple[UUID, int], str] = {}

    @staticmethod
    def _append_static(
        key: UUID,
        value: Instrument | Venue,
        values: dict[UUID, Instrument | Venue],
        hashes: dict[UUID, str],
        *,
        conflict_code: str,
    ) -> bool:
        digest = value.sha256()
        existing = hashes.get(key)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(f"{conflict_code}:{key}")
            return False
        values[key] = value
        hashes[key] = digest
        return True

    def add_instrument(self, instrument: Instrument) -> bool:
        return self._append_static(
            instrument.instrument_id,
            instrument,
            self._instruments,
            self._instrument_hashes,
            conflict_code="INSTRUMENT_ID_CONFLICT",
        )

    def add_venue(self, venue: Venue) -> bool:
        existing_id = self._venue_by_mic.get(venue.mic)
        if existing_id is not None and existing_id != venue.venue_id:
            raise DuplicateConflict(f"MIC_CONFLICT:{venue.mic}")
        inserted = self._append_static(
            venue.venue_id,
            venue,
            self._venues,
            self._venue_hashes,
            conflict_code="VENUE_ID_CONFLICT",
        )
        self._venue_by_mic[venue.mic] = venue.venue_id
        return inserted

    def append_listing(self, listing: ListingVersion) -> bool:
        if listing.instrument_id not in self._instruments:
            raise InvariantViolation(f"UNKNOWN_INSTRUMENT:{listing.instrument_id}")
        if listing.venue_id not in self._venues:
            raise InvariantViolation(f"UNKNOWN_VENUE:{listing.venue_id}")
        key = (listing.listing_id, listing.version)
        digest = listing.sha256()
        existing = self._listing_hashes.get(key)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(f"LISTING_VERSION_CONFLICT:{listing.listing_id}:{listing.version}")
            return False
        history = self._listings.setdefault(listing.listing_id, [])
        expected = len(history) + 1
        if listing.version != expected:
            raise InvariantViolation(
                f"LISTING_VERSION_SEQUENCE:expected={expected}:actual={listing.version}"
            )
        if history:
            previous = history[-1]
            if listing.revision_time_ns < previous.revision_time_ns:
                raise InvariantViolation("LISTING_REVISION_TIME_REGRESSION")
            if listing.instrument_id != previous.instrument_id or listing.venue_id != previous.venue_id:
                raise InvariantViolation("LISTING_IDENTITY_MUTATION")
        history.append(listing)
        self._listing_hashes[key] = digest
        return True

    def append_identifier(self, assignment: IdentifierAssignment) -> bool:
        if (
            assignment.entity_id not in self._instruments
            and assignment.entity_id not in self._venues
            and assignment.entity_id not in self._listings
        ):
            raise InvariantViolation(f"UNKNOWN_IDENTIFIER_ENTITY:{assignment.entity_id}")
        key = (assignment.assignment_id, assignment.version)
        digest = assignment.sha256()
        existing = self._identifier_hashes.get(key)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(
                    f"IDENTIFIER_VERSION_CONFLICT:{assignment.assignment_id}:{assignment.version}"
                )
            return False
        history = self._identifiers.setdefault(assignment.assignment_id, [])
        expected = len(history) + 1
        if assignment.version != expected:
            raise InvariantViolation(
                f"IDENTIFIER_VERSION_SEQUENCE:expected={expected}:actual={assignment.version}"
            )
        if history and assignment.entity_id != history[-1].entity_id:
            raise InvariantViolation("IDENTIFIER_ASSIGNMENT_ENTITY_MUTATION")
        history.append(assignment)
        self._identifier_hashes[key] = digest
        return True

    @staticmethod
    def _latest_known(
        records: Iterable[ListingVersion | IdentifierAssignment],
        *,
        knowledge_time_ns: int,
    ) -> ListingVersion | IdentifierAssignment | None:
        known = [
            record
            for record in records
            if record.available_to_strategy_at_ns <= knowledge_time_ns
        ]
        if not known:
            return None
        return max(known, key=lambda record: (record.revision_time_ns, record.version))

    def resolve_symbol(
        self,
        symbol: str,
        mic: str,
        *,
        economic_time_ns: int,
        knowledge_time_ns: int,
    ) -> ListingVersion | None:
        _time(economic_time_ns, "INVALID_ECONOMIC_TIME")
        _time(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
        venue_id = self._venue_by_mic.get(mic.upper())
        if venue_id is None:
            return None
        normalized_symbol = symbol.strip().upper()
        candidates: list[ListingVersion] = []
        for history in self._listings.values():
            latest = self._latest_known(history, knowledge_time_ns=knowledge_time_ns)
            if (
                isinstance(latest, ListingVersion)
                and latest.visible(
                    economic_time_ns=economic_time_ns,
                    knowledge_time_ns=knowledge_time_ns,
                )
                and latest.venue_id == venue_id
                and latest.symbol == normalized_symbol
            ):
                candidates.append(latest)
        if len(candidates) > 1:
            raise AmbiguousIdentity(
                f"AMBIGUOUS_SYMBOL:{normalized_symbol}:{mic.upper()}:{economic_time_ns}:{knowledge_time_ns}"
            )
        return candidates[0] if candidates else None

    def resolve_identifier(
        self,
        identifier_type: IdentifierType,
        value: str,
        *,
        economic_time_ns: int,
        knowledge_time_ns: int,
    ) -> IdentifierAssignment | None:
        if not isinstance(identifier_type, IdentifierType):
            raise InvariantViolation("INVALID_IDENTIFIER_TYPE")
        normalized = value.strip().upper()
        candidates: list[IdentifierAssignment] = []
        for history in self._identifiers.values():
            latest = self._latest_known(history, knowledge_time_ns=knowledge_time_ns)
            if (
                isinstance(latest, IdentifierAssignment)
                and latest.visible(
                    economic_time_ns=economic_time_ns,
                    knowledge_time_ns=knowledge_time_ns,
                )
                and latest.identifier_type is identifier_type
                and latest.value == normalized
            ):
                candidates.append(latest)
        entity_ids = {candidate.entity_id for candidate in candidates}
        if len(entity_ids) > 1:
            raise AmbiguousIdentity(
                f"AMBIGUOUS_IDENTIFIER:{identifier_type.value}:{normalized}"
            )
        return max(candidates, key=lambda item: (item.revision_time_ns, item.version)) if candidates else None

    def listing_history(self, listing_id: UUID) -> tuple[ListingVersion, ...]:
        return tuple(self._listings.get(listing_id, ()))

    def identifier_history(self, assignment_id: UUID) -> tuple[IdentifierAssignment, ...]:
        return tuple(self._identifiers.get(assignment_id, ()))
