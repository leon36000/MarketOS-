"""Append-only exact double-entry ledger."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .canonical import canonical_sha256
from .errors import DuplicateConflict, InvariantViolation
from .money import Money


class PostingSide(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

    def opposite(self) -> "PostingSide":
        return PostingSide.CREDIT if self is PostingSide.DEBIT else PostingSide.DEBIT


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    side: PostingSide
    amount: Money

    def __post_init__(self) -> None:
        if not self.account.strip():
            raise InvariantViolation("MISSING_LEDGER_ACCOUNT")
        if not isinstance(self.side, PostingSide):
            raise InvariantViolation("INVALID_POSTING_SIDE")
        if self.amount.minor_units <= 0:
            raise InvariantViolation("POSTING_AMOUNT_MUST_BE_POSITIVE")

    def canonical_dict(self) -> dict[str, object]:
        return {"account": self.account, "side": self.side, "amount": self.amount}


@dataclass(frozen=True, slots=True)
class JournalEntry:
    entry_id: str
    occurred_at_ns: int
    description: str
    postings: tuple[Posting, ...]
    reversal_of: str | None = None

    def __post_init__(self) -> None:
        if not self.entry_id.strip():
            raise InvariantViolation("MISSING_JOURNAL_ENTRY_ID")
        if isinstance(self.occurred_at_ns, bool) or not isinstance(self.occurred_at_ns, int) or self.occurred_at_ns < 0:
            raise InvariantViolation("INVALID_JOURNAL_TIME")
        if not self.description.strip():
            raise InvariantViolation("MISSING_JOURNAL_DESCRIPTION")
        postings = tuple(self.postings)
        if len(postings) < 2:
            raise InvariantViolation("JOURNAL_ENTRY_REQUIRES_TWO_POSTINGS")
        totals: dict[str, dict[PostingSide, int]] = {}
        for posting in postings:
            currency_totals = totals.setdefault(
                posting.amount.currency,
                {PostingSide.DEBIT: 0, PostingSide.CREDIT: 0},
            )
            currency_totals[posting.side] += posting.amount.minor_units
        if any(values[PostingSide.DEBIT] != values[PostingSide.CREDIT] for values in totals.values()):
            raise InvariantViolation("UNBALANCED_JOURNAL_ENTRY")
        object.__setattr__(self, "postings", postings)

    def canonical_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "occurred_at_ns": self.occurred_at_ns,
            "description": self.description,
            "postings": self.postings,
            "reversal_of": self.reversal_of,
        }

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())


class Ledger:
    """In-memory append-only ledger with idempotent stable entry IDs."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._hashes: dict[str, str] = {}
        self._balances: dict[tuple[str, str], int] = {}
        self._reversed_by: dict[str, str] = {}

    def post(self, entry: JournalEntry) -> bool:
        digest = entry.sha256()
        existing = self._hashes.get(entry.entry_id)
        if existing is not None:
            if existing != digest:
                raise DuplicateConflict(f"JOURNAL_ENTRY_ID_CONFLICT:{entry.entry_id}")
            return False
        for posting in entry.postings:
            key = (posting.account, posting.amount.currency)
            signed = posting.amount.minor_units if posting.side is PostingSide.DEBIT else -posting.amount.minor_units
            self._balances[key] = self._balances.get(key, 0) + signed
        self._entries.append(entry)
        self._hashes[entry.entry_id] = digest
        if entry.reversal_of is not None:
            self._reversed_by[entry.reversal_of] = entry.entry_id
        return True

    def post_many(self, entries: Iterable[JournalEntry]) -> tuple[bool, ...]:
        # Validate duplicate/conflict state against a clone before mutating.
        pending = tuple(entries)
        clone = self.clone()
        results = tuple(clone.post(entry) for entry in pending)
        self._entries = clone._entries
        self._hashes = clone._hashes
        self._balances = clone._balances
        self._reversed_by = clone._reversed_by
        return results

    def reverse(
        self,
        entry_id: str,
        *,
        reversal_id: str,
        occurred_at_ns: int,
        description: str | None = None,
    ) -> JournalEntry:
        if entry_id in self._reversed_by:
            raise InvariantViolation(f"JOURNAL_ENTRY_ALREADY_REVERSED:{entry_id}")
        original = next((entry for entry in self._entries if entry.entry_id == entry_id), None)
        if original is None:
            raise InvariantViolation(f"UNKNOWN_JOURNAL_ENTRY:{entry_id}")
        reversal = JournalEntry(
            entry_id=reversal_id,
            occurred_at_ns=occurred_at_ns,
            description=description or f"Reverse {entry_id}",
            postings=tuple(
                Posting(posting.account, posting.side.opposite(), posting.amount)
                for posting in original.postings
            ),
            reversal_of=entry_id,
        )
        self.post(reversal)
        return reversal

    def balance(self, account: str, currency: str) -> Money:
        return Money(currency, self._balances.get((account, currency.upper()), 0))

    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    def clone(self) -> "Ledger":
        clone = Ledger()
        clone._entries = list(self._entries)
        clone._hashes = dict(self._hashes)
        clone._balances = dict(self._balances)
        clone._reversed_by = dict(self._reversed_by)
        return clone

    def canonical_dict(self) -> dict[str, object]:
        return {"entries": tuple(entry.canonical_dict() for entry in self._entries)}

    def sha256(self) -> str:
        return canonical_sha256(self.canonical_dict())
