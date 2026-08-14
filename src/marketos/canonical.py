"""Canonical JSON and SHA-256 helpers used by evidence and state fingerprints."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from .errors import InvariantViolation


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise InvariantViolation("NON_FINITE_DECIMAL")
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def to_canonical_primitive(value: Any) -> Any:
    """Convert supported objects to a stable JSON-compatible representation.

    Binary floating point is deliberately forbidden.  Callers must use an
    integer, a Decimal created from text, or a dedicated exact domain type.
    """

    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        raise InvariantViolation("FLOAT_FORBIDDEN")
    if isinstance(value, Decimal):
        return {"$decimal": _decimal_text(value)}
    if isinstance(value, Enum):
        return to_canonical_primitive(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvariantViolation("NAIVE_DATETIME_FORBIDDEN")
        canonical = value.astimezone(timezone.utc).isoformat(timespec="microseconds")
        return {"$datetime": canonical.replace("+00:00", "Z")}
    if isinstance(value, UUID):
        return {"$uuid": str(value)}
    if isinstance(value, Path):
        return {"$path": value.as_posix()}
    if is_dataclass(value) and not isinstance(value, type):
        return to_canonical_primitive(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): to_canonical_primitive(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [to_canonical_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [to_canonical_primitive(item) for item in value]
        return sorted(converted, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    canonical_method = getattr(value, "canonical_dict", None)
    if callable(canonical_method):
        return to_canonical_primitive(canonical_method())
    raise InvariantViolation(f"UNSUPPORTED_CANONICAL_TYPE:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        to_canonical_primitive(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
