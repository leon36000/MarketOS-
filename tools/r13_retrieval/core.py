"""Shared R13 retrieval contracts, types, hashes, and URL helpers."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

MANIFEST_SCHEMA = "marketos.r13-source-content-manifest.v1"
SOURCE_SHARD_SCHEMA = "marketos.r13-source-content-source-shard.v1"
RETRIEVAL_SCHEMA = "marketos.r13-source-content-retrieval.v1"
BUNDLE_SCHEMA = "marketos.r13-source-content-receipt-bundle.v1"
RUN_SCHEMA = "marketos.r13-source-content-run-receipt.v1"
FAIL_CLOSED_RIGHTS = (
    "RETRIEVAL_AND_HASH_ONLY_NO_REDISTRIBUTION_OR_TRAINING_RIGHT_ASSERTED"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
FIXED_ZIP_DT = (1980, 1, 1, 0, 0, 0)
DEFAULT_USER_AGENT = (
    "MarketOS-R13-Research-Retriever/1.0 "
    "(+https://github.com/leon36000/MarketOS-)"
)
REQUIRED_BUNDLE_FILES = {
    "README.md",
    "SOURCE_CONTENT_RECEIPTS.json",
    "SOURCE_RIGHTS_MATRIX.json",
    "RETRIEVAL_FAILURES.json",
    "SOURCE_RETRIEVAL_SUMMARY.json",
    "BUNDLE_MANIFEST.json",
}


class ManifestError(ValueError):
    """Raised when the retrieval manifest violates a fail-closed contract."""


class RetrievalError(RuntimeError):
    """Raised when required retrieval or bundle validation fails."""


@dataclass(frozen=True)
class FetchResponse:
    status: int
    final_url: str
    content_type: str
    body: bytes
    headers: Mapping[str, str]


Fetcher = Callable[..., FetchResponse]


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _domain(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.hostname or "").lower().rstrip(".")


def _domain_allowed(domain: str, allowed: Sequence[str]) -> bool:
    return any(domain == item or domain.endswith("." + item) for item in allowed)


def _as_nonempty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{name} must be a non-empty string")
    return value.strip()
