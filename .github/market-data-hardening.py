#!/usr/bin/env python3
from pathlib import Path

path = Path("src/marketos/marketdata.py")
text = path.read_text(encoding="utf-8")
old = '''        kind = ObservationKind(str(row["kind"]))
        observation = MarketObservation(
'''
new = '''        kind = ObservationKind(str(row["kind"]))
        try:
            payload = cls._payload_from_json(kind, str(row["payload_json"]))
        except (InvariantViolation, KeyError, TypeError, ValueError) as exc:
            raise InvariantViolation(
                f"MARKET_OBSERVATION_HASH_MISMATCH:{row['observation_id']}:{row['version']}"
            ) from exc
        observation = MarketObservation(
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one observation-read patch site, found {text.count(old)}")
text = text.replace(old, new, 1)
old_payload = '''            payload=cls._payload_from_json(kind, str(row["payload_json"])),
'''
new_payload = '''            payload=payload,
'''
if text.count(old_payload) != 1:
    raise SystemExit(f"expected one payload patch site, found {text.count(old_payload)}")
path.write_text(text.replace(old_payload, new_payload, 1), encoding="utf-8")
