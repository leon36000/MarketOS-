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


# Persist the exact quality and rights policies that authorized admission.
replace_once(
    "src/marketos/marketdata.py",
    '''    observation_sha256: str
    quality_decision_sha256: str
    inserted: bool
''',
    '''    observation_sha256: str
    quality_policy_sha256: str
    rights_policy_sha256: str
    quality_decision_sha256: str
    inserted: bool
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''            "observation_sha256": self.observation_sha256,
            "quality_decision_sha256": self.quality_decision_sha256,
''',
    '''            "observation_sha256": self.observation_sha256,
            "quality_policy_sha256": self.quality_policy_sha256,
            "rights_policy_sha256": self.rights_policy_sha256,
            "quality_decision_sha256": self.quality_decision_sha256,
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''                observation_sha256 TEXT NOT NULL,
                quality_state TEXT NOT NULL,
''',
    '''                observation_sha256 TEXT NOT NULL,
                quality_policy_sha256 TEXT NOT NULL,
                rights_policy_sha256 TEXT NOT NULL,
                quality_state TEXT NOT NULL,
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''    @classmethod
    def _observation_from_row(cls, row: sqlite3.Row) -> MarketObservation:
        kind = ObservationKind(str(row["kind"]))
        try:
            payload = cls._payload_from_json(kind, str(row["payload_json"]))
''',
    '''    def _observation_from_row(self, row: sqlite3.Row) -> MarketObservation:
        kind = ObservationKind(str(row["kind"]))
        try:
            payload = self._payload_from_json(kind, str(row["payload_json"]))
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''        if observation.sha256() != str(row["observation_sha256"]):
            raise InvariantViolation(
                f"MARKET_OBSERVATION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        decision_payload = {
            "observation_sha256": observation.sha256(),
            "quality_state": QualityState(str(row["quality_state"])),
            "reasons": tuple(json.loads(row["reasons_json"])),
        }
        if canonical_sha256(decision_payload) != str(row["quality_decision_sha256"]):
            raise InvariantViolation(
                f"MARKET_QUALITY_DECISION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        return observation
''',
    '''        if observation.sha256() != str(row["observation_sha256"]):
            raise InvariantViolation(
                f"MARKET_OBSERVATION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        if not self.raw_evidence_store.verify(observation.raw_content_sha256):
            raise InvariantViolation(
                f"MARKET_RAW_EVIDENCE_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        try:
            quality_state = QualityState(str(row["quality_state"]))
            reasons_value = json.loads(row["reasons_json"])
            if not isinstance(reasons_value, list) or any(
                not isinstance(reason, str) for reason in reasons_value
            ):
                raise ValueError("invalid reasons")
            reasons = tuple(reasons_value)
            quality_policy_sha256 = str(row["quality_policy_sha256"])
            rights_policy_sha256 = str(row["rights_policy_sha256"])
            if not _HEX64.fullmatch(quality_policy_sha256) or not _HEX64.fullmatch(
                rights_policy_sha256
            ):
                raise ValueError("invalid policy hash")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise InvariantViolation(
                f"MARKET_QUALITY_DECISION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            ) from exc
        decision_payload = {
            "observation_sha256": observation.sha256(),
            "quality_policy_sha256": quality_policy_sha256,
            "rights_policy_sha256": rights_policy_sha256,
            "quality_state": quality_state,
            "reasons": reasons,
        }
        if canonical_sha256(decision_payload) != str(row["quality_decision_sha256"]):
            raise InvariantViolation(
                f"MARKET_QUALITY_DECISION_HASH_MISMATCH:{observation.observation_id}:{observation.version}"
            )
        return observation
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''            observation_sha256=str(row["observation_sha256"]),
            quality_decision_sha256=str(row["quality_decision_sha256"]),
''',
    '''            observation_sha256=str(row["observation_sha256"]),
            quality_policy_sha256=str(row["quality_policy_sha256"]),
            rights_policy_sha256=str(row["rights_policy_sha256"]),
            quality_decision_sha256=str(row["quality_decision_sha256"]),
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''        self._require_rights(rights_policy)
        observation_sha = observation.sha256()
''',
    '''        self._require_rights(rights_policy)
        observation_sha = observation.sha256()
        quality_policy_sha256 = quality_policy.sha256()
        rights_policy_sha256 = rights_policy.sha256()
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''                if str(existing["observation_sha256"]) != observation_sha:
                    raise DuplicateConflict(
                        f"MARKET_OBSERVATION_VERSION_CONFLICT:{observation.observation_id}:{observation.version}"
                    )
                self._observation_from_row(existing)
''',
    '''                if str(existing["observation_sha256"]) != observation_sha:
                    raise DuplicateConflict(
                        f"MARKET_OBSERVATION_VERSION_CONFLICT:{observation.observation_id}:{observation.version}"
                    )
                if (
                    str(existing["quality_policy_sha256"]) != quality_policy_sha256
                    or str(existing["rights_policy_sha256"]) != rights_policy_sha256
                ):
                    raise DuplicateConflict(
                        f"INGESTION_POLICY_CONFLICT:{observation.observation_id}:{observation.version}"
                    )
                self._observation_from_row(existing)
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''            decision_payload = {
                "observation_sha256": observation_sha,
                "quality_state": quality_state,
                "reasons": reasons_tuple,
            }
''',
    '''            decision_payload = {
                "observation_sha256": observation_sha,
                "quality_policy_sha256": quality_policy_sha256,
                "rights_policy_sha256": rights_policy_sha256,
                "quality_state": quality_state,
                "reasons": reasons_tuple,
            }
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''                    observation_sha256, quality_state, reasons_json,
                    quality_decision_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''',
    '''                    observation_sha256, quality_policy_sha256,
                    rights_policy_sha256, quality_state, reasons_json,
                    quality_decision_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''',
)
replace_once(
    "src/marketos/marketdata.py",
    '''                    observation_sha,
                    quality_state.value,
''',
    '''                    observation_sha,
                    quality_policy_sha256,
                    rights_policy_sha256,
                    quality_state.value,
''',
)

# Derived bars require explicit rights and preserve the rights-policy hash.
replace_once(
    "src/marketos/bars.py",
    '''from decimal import Decimal
from typing import Iterable
''',
    '''from decimal import Decimal
import re
from typing import Iterable
''',
)
replace_once(
    "src/marketos/bars.py",
    '''from .errors import InvariantViolation
''',
    '''from .errors import DomainError, InvariantViolation
''',
)
replace_once(
    "src/marketos/bars.py",
    '''from .money import Price, Quantity


def _nonnegative_int''',
    '''from .money import Price, Quantity
from .rights import RightsPolicy


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BarDerivationDenied(DomainError):
    """Raised when data rights do not permit the requested derived view."""


def _nonnegative_int''',
)
replace_once(
    "src/marketos/bars.py",
    '''    input_root_sha256: str
    live_trading_state: str = "HARD_LOCKED"
''',
    '''    input_root_sha256: str
    rights_policy_sha256: str
    live_trading_state: str = "HARD_LOCKED"
''',
)
replace_once(
    "src/marketos/bars.py",
    '''        if len(self.input_root_sha256) != 64:
            raise InvariantViolation("INVALID_BAR_INPUT_ROOT")
''',
    '''        if not _HEX64.fullmatch(self.input_root_sha256):
            raise InvariantViolation("INVALID_BAR_INPUT_ROOT")
        if not _HEX64.fullmatch(self.rights_policy_sha256):
            raise InvariantViolation("INVALID_BAR_RIGHTS_POLICY_HASH")
''',
)
replace_once(
    "src/marketos/bars.py",
    '''            "input_root_sha256": self.input_root_sha256,
            "live_trading_state": self.live_trading_state,
''',
    '''            "input_root_sha256": self.input_root_sha256,
            "rights_policy_sha256": self.rights_policy_sha256,
            "live_trading_state": self.live_trading_state,
''',
)
replace_once(
    "src/marketos/bars.py",
    '''    seen_versions: set[tuple[str, int]] = set()
    latest: dict[str, MarketObservation] = {}
    for observation in observations:
        key = (observation.observation_id, observation.version)
        if key in seen_versions:
            raise InvariantViolation(
                f"DUPLICATE_TRADE_OBSERVATION:{observation.observation_id}:{observation.version}"
            )
        seen_versions.add(key)
        if observation.kind is not ObservationKind.TRADE:
            continue
        if observation.time.available_at_ns > knowledge_time_ns:
            continue
        previous = latest.get(observation.observation_id)
''',
    '''    seen_versions: set[tuple[str, int]] = set()
    identities: dict[str, tuple[object, ...]] = {}
    latest: dict[str, MarketObservation] = {}
    for observation in observations:
        key = (observation.observation_id, observation.version)
        if key in seen_versions:
            raise InvariantViolation(
                f"DUPLICATE_TRADE_OBSERVATION:{observation.observation_id}:{observation.version}"
            )
        seen_versions.add(key)
        if observation.kind is not ObservationKind.TRADE:
            continue
        if observation.time.available_at_ns > knowledge_time_ns:
            continue
        identity = (
            observation.kind,
            observation.listing_id,
            observation.venue_id,
            observation.source_id,
            observation.channel_id,
            observation.time.event_time_ns,
        )
        previous_identity = identities.setdefault(observation.observation_id, identity)
        if previous_identity != identity:
            raise InvariantViolation(
                f"BAR_OBSERVATION_IDENTITY_MUTATION:{observation.observation_id}"
            )
        previous = latest.get(observation.observation_id)
''',
)
replace_once(
    "src/marketos/bars.py",
    '''    interval_ns: int,
    knowledge_time_ns: int,
) -> tuple[TradeBar, ...]:
''',
    '''    interval_ns: int,
    knowledge_time_ns: int,
    rights_policy: RightsPolicy,
) -> tuple[TradeBar, ...]:
''',
)
replace_once(
    "src/marketos/bars.py",
    '''    _nonnegative_int(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")

    trades = _latest_known_trades(
''',
    '''    _nonnegative_int(knowledge_time_ns, "INVALID_KNOWLEDGE_TIME")
    for capability in ("non_display", "historical_replay", "derived_data"):
        if not rights_policy.allows(capability):
            raise BarDerivationDenied(
                f"BAR_DERIVATION_RIGHT_DENIED:{rights_policy.policy_id}:{capability}"
            )
    rights_policy_sha256 = rights_policy.sha256()

    trades = _latest_known_trades(
''',
)
replace_once(
    "src/marketos/bars.py",
    '''                input_root_sha256=input_root,
            )
''',
    '''                input_root_sha256=input_root,
                rights_policy_sha256=rights_policy_sha256,
            )
''',
)

# Existing deterministic-bar tests now supply an explicit, complete policy.
test_bars = Path("tests/test_bars.py")
test_bars.write_text(
    '''from __future__ import annotations

from decimal import Decimal
import unittest
from uuid import UUID

from marketos.bars import build_trade_bars
from marketos.marketdata import (
    MarketObservation,
    ObservationKind,
    ObservationStatus,
    TradePayload,
)
from marketos.money import Price, Quantity
from marketos.rights import REQUIRED_RIGHTS_FIELDS, RightDecision, RightsPolicy
from marketos.time import EventTime


LISTING_ID = UUID("00000000-0000-0000-0000-000000004100")
VENUE_ID = UUID("00000000-0000-0000-0000-000000004010")


class BarTests(unittest.TestCase):
    @staticmethod
    def rights() -> RightsPolicy:
        fields = {field: RightDecision.DENY for field in REQUIRED_RIGHTS_FIELDS}
        for field in ("non_display", "historical_replay", "derived_data"):
            fields[field] = RightDecision.ALLOW
        return RightsPolicy("bar-rights", fields)

    @staticmethod
    def trade(observation_id: str, sequence: int, event_ns: int, available_ns: int, price: str, size: str) -> MarketObservation:
        return MarketObservation(
            observation_id=observation_id,
            version=1,
            kind=ObservationKind.TRADE,
            status=ObservationStatus.ORIGINAL,
            listing_id=LISTING_ID,
            venue_id=VENUE_ID,
            source_id="fixture",
            channel_id="trades",
            source_sequence=sequence,
            time=EventTime(event_ns, available_ns, available_ns, available_ns),
            raw_content_sha256=(hex(sequence)[2:] * 64)[:64].ljust(64, "0"),
            schema_version="trade@1",
            payload=TradePayload(
                price=Price.parse("USD", price, tick_size="0.01"),
                size=Quantity.positive(size),
                condition_codes=(),
            ),
        )

    def test_bar_is_deterministic_exact_and_has_no_lookahead(self) -> None:
        early = self.trade("early", 1, 10, 20, "100", "2")
        middle = self.trade("middle", 2, 20, 30, "105", "3")
        close = self.trade("close", 3, 90, 95, "102", "1")
        late_arrival = self.trade("late-arrival", 4, 80, 120, "110", "4")

        first = build_trade_bars(
            (close, middle, early, late_arrival),
            interval_ns=100,
            knowledge_time_ns=100,
            rights_policy=self.rights(),
        )
        second = build_trade_bars(
            (early, late_arrival, close, middle),
            interval_ns=100,
            knowledge_time_ns=100,
            rights_policy=self.rights(),
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        bar = first[0]
        self.assertEqual(bar.open.value, Decimal("100"))
        self.assertEqual(bar.high.value, Decimal("105"))
        self.assertEqual(bar.low.value, Decimal("100"))
        self.assertEqual(bar.close.value, Decimal("102"))
        self.assertEqual(bar.volume.value, Decimal("6"))
        self.assertEqual(bar.trade_count, 3)
        self.assertEqual(bar.available_to_strategy_at_ns, 100)
        self.assertEqual(bar.rights_policy_sha256, self.rights().sha256())

        revised = build_trade_bars(
            (early, middle, close, late_arrival),
            interval_ns=100,
            knowledge_time_ns=130,
            rights_policy=self.rights(),
        )
        self.assertEqual(revised[0].high.value, Decimal("110"))
        self.assertEqual(revised[0].volume.value, Decimal("10"))
        self.assertEqual(revised[0].available_to_strategy_at_ns, 120)
        self.assertNotEqual(revised[0].input_root_sha256, bar.input_root_sha256)

    def test_incomplete_bucket_is_not_published(self) -> None:
        trade = self.trade("future-bucket", 1, 110, 120, "100", "1")
        self.assertEqual(
            build_trade_bars(
                (trade,),
                interval_ns=100,
                knowledge_time_ns=150,
                rights_policy=self.rights(),
            ),
            (),
        )
        self.assertEqual(
            len(
                build_trade_bars(
                    (trade,),
                    interval_ns=100,
                    knowledge_time_ns=200,
                    rights_policy=self.rights(),
                )
            ),
            1,
        )

    def test_duplicate_trade_identity_is_rejected(self) -> None:
        trade = self.trade("dup", 1, 10, 20, "100", "1")
        with self.assertRaisesRegex(Exception, "DUPLICATE_TRADE_OBSERVATION"):
            build_trade_bars(
                (trade, trade),
                interval_ns=100,
                knowledge_time_ns=100,
                rights_policy=self.rights(),
            )


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)

# The independent verifier supplies rights and checks admission provenance.
replace_once(
    "tools/verify_market_data.py",
    '''                _require(first.quality_state is QualityState.ACCEPTED, "FIRST_SEQUENCE_REJECTED")
''',
    '''                _require(first.quality_state is QualityState.ACCEPTED, "FIRST_SEQUENCE_REJECTED")
                _require(first.quality_policy_sha256 == _quality().sha256(), "QUALITY_POLICY_HASH_MISSING")
                _require(first.rights_policy_sha256 == _rights().sha256(), "RIGHTS_POLICY_HASH_MISSING")
''',
)
replace_count(
    "tools/verify_market_data.py",
    '''                knowledge_time_ns=100,
            )
''',
    '''                knowledge_time_ns=100,
                rights_policy=_rights(),
            )
''',
    2,
)
replace_once(
    "tools/verify_market_data.py",
    '''                knowledge_time_ns=130,
            )
''',
    '''                knowledge_time_ns=130,
                rights_policy=_rights(),
            )
''',
)

replace_once(
    "docs/implementation/CANONICAL_MARKET_DATA.md",
    '''- stored observation and quality-decision hash verification on read;
- accepted and quarantined streams kept distinct;
- exact deterministic OHLCV bars with complete-bucket and no-look-ahead rules;
''',
    '''- stored observation, raw-source and quality-decision hash verification on read;
- exact quality-policy and rights-policy hashes preserved in every admission decision;
- accepted and quarantined streams kept distinct;
- exact deterministic OHLCV bars with complete-bucket, no-look-ahead and explicit derived-data rights;
''',
)
replace_once(
    "docs/implementation/CANONICAL_MARKET_DATA_REVIEW.md",
    '''3. The permanent derived-file workflow now runs foundation, Data Fabric and market-data acceptance verifiers and watches the permanent data workflows.
''',
    '''3. The permanent derived-file workflow now runs foundation, Data Fabric and market-data acceptance verifiers and watches the permanent data workflows.
4. Admission decisions now preserve quality- and rights-policy hashes; a duplicate under different policy is a conflict.
5. Canonical reads re-verify the referenced raw bytes, and bar derivation requires and records explicit rights.
6. Bar revisions cannot mutate listing, venue, source, channel or economic identity.
''',
)
