"""Fail-closed R13 manifest and source-shard loading."""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from .core import (
    FAIL_CLOSED_RIGHTS,
    MANIFEST_SCHEMA,
    SAFE_ID_RE,
    SOURCE_SHARD_SCHEMA,
    ManifestError,
    _as_nonempty_str,
    _domain,
    _domain_allowed,
    sha256_file,
)


def validate_manifest(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if value.get("schema_version") != MANIFEST_SCHEMA:
        raise ManifestError(f"schema_version must be {MANIFEST_SCHEMA}")
    if value.get("classification") != "PREPHASE_RESEARCH_INPUT_NOT_PHASE_CLOSURE":
        raise ManifestError("manifest classification must remain prephase")

    allowed_domains = value.get("allowed_domains")
    if not isinstance(allowed_domains, list) or not allowed_domains:
        raise ManifestError("allowed_domains must be a non-empty list")
    normalized_domains: list[str] = []
    for item in allowed_domains:
        domain = _as_nonempty_str(item, "allowed domain").lower().rstrip(".")
        if "/" in domain or ":" in domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise ManifestError(f"invalid allowed domain: {item!r}")
        normalized_domains.append(domain)
    if len(set(normalized_domains)) != len(normalized_domains):
        raise ManifestError("allowed_domains contains duplicates")

    hard_locks = value.get("hard_locks")
    if not isinstance(hard_locks, Mapping):
        raise ManifestError("hard_locks missing")
    expected_locks = {
        "live_trading": "HARD_LOCKED",
        "profitability": "UNPROVEN",
        "project_complete": False,
        "production_ready": False,
    }
    for key, expected in expected_locks.items():
        if hard_locks.get(key) != expected:
            raise ManifestError(f"hard lock {key} must be {expected!r}")

    thresholds = value.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise ManifestError("thresholds missing")
    minimum_successes = thresholds.get("minimum_successes")
    if not isinstance(minimum_successes, int) or minimum_successes < 0:
        raise ManifestError("minimum_successes must be a non-negative integer")
    minimum_by_category = thresholds.get("minimum_by_category")
    if not isinstance(minimum_by_category, Mapping):
        raise ManifestError("minimum_by_category must be an object")
    for category, count in minimum_by_category.items():
        _as_nonempty_str(category, "threshold category")
        if not isinstance(count, int) or count < 0:
            raise ManifestError(f"invalid minimum for {category}")

    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ManifestError("sources must be a non-empty list")
    ids: set[str] = set()
    urls: set[str] = set()
    for index, item in enumerate(sources):
        if not isinstance(item, Mapping):
            raise ManifestError(f"sources[{index}] must be an object")
        source_id = _as_nonempty_str(item.get("source_id"), f"sources[{index}].source_id")
        if not SAFE_ID_RE.fullmatch(source_id):
            raise ManifestError(f"unsafe source_id: {source_id!r}")
        if source_id in ids:
            raise ManifestError(f"duplicate source_id: {source_id}")
        ids.add(source_id)
        url = _as_nonempty_str(item.get("url"), f"sources[{index}].url")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ManifestError(f"source URL must be credential-free HTTPS: {url}")
        if not _domain_allowed(_domain(url), normalized_domains):
            raise ManifestError(f"source domain is not allowlisted: {url}")
        normalized_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, "")
        )
        if normalized_url in urls:
            raise ManifestError(f"duplicate source URL: {url}")
        urls.add(normalized_url)
        _as_nonempty_str(item.get("title"), f"sources[{index}].title")
        _as_nonempty_str(item.get("category"), f"sources[{index}].category")
        _as_nonempty_str(item.get("authority_class"), f"sources[{index}].authority_class")
        if item.get("rights_class") != FAIL_CLOSED_RIGHTS:
            raise ManifestError(f"source {source_id} must use fail-closed rights class")
        if not isinstance(item.get("required"), bool):
            raise ManifestError(f"source {source_id} required must be boolean")
        max_bytes = item.get("max_bytes")
        if not isinstance(max_bytes, int) or max_bytes <= 0 or max_bytes > 100_000_000:
            raise ManifestError(f"source {source_id} max_bytes is invalid")
        content_types = item.get("expected_content_types")
        if not isinstance(content_types, list) or not content_types:
            raise ManifestError(f"source {source_id} expected_content_types missing")
        if any(not isinstance(t, str) or "/" not in t for t in content_types):
            raise ManifestError(f"source {source_id} expected_content_types invalid")
        if "summary" in item and (
            not isinstance(item["summary"], str) or len(item["summary"]) > 600
        ):
            raise ManifestError(f"source {source_id} summary must be <= 600 characters")

    if minimum_successes > len(sources):
        raise ManifestError("minimum_successes exceeds source count")
    categories = {str(item["category"]) for item in sources}
    missing_threshold_categories = set(minimum_by_category) - categories
    if missing_threshold_categories:
        raise ManifestError(
            f"threshold categories absent from sources: {sorted(missing_threshold_categories)}"
        )
    return value


def _safe_shard_path(root: Path, value: object) -> Path:
    relative = Path(_as_nonempty_str(value, "source shard path"))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".json":
        raise ManifestError(f"unsafe source shard path: {relative}")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ManifestError(f"source shard escapes manifest directory: {relative}")
    return resolved


def load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ManifestError("manifest root must be an object")

    source_files = value.get("source_files")
    if source_files is None:
        return validate_manifest(value)
    if not isinstance(source_files, list) or not source_files:
        raise ManifestError("source_files must be a non-empty list")
    if value.get("sources") not in (None, []):
        raise ManifestError("manifest cannot mix inline sources and source_files")
    if len(source_files) != len(set(map(str, source_files))):
        raise ManifestError("source_files contains duplicates")

    sources: list[Mapping[str, Any]] = []
    shard_receipts: list[dict[str, Any]] = []
    for declared in source_files:
        shard_path = _safe_shard_path(path.parent, declared)
        try:
            shard = json.loads(shard_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"cannot read source shard {declared}: {exc}") from exc
        if not isinstance(shard, Mapping) or shard.get("schema_version") != SOURCE_SHARD_SCHEMA:
            raise ManifestError(f"invalid source shard schema: {declared}")
        shard_sources = shard.get("sources")
        if not isinstance(shard_sources, list) or not shard_sources:
            raise ManifestError(f"source shard contains no sources: {declared}")
        category = shard.get("category")
        if category is not None and any(
            item.get("category") != category for item in shard_sources
        ):
            raise ManifestError(f"source shard category mismatch: {declared}")
        sources.extend(shard_sources)
        shard_receipts.append(
            {
                "path": Path(str(declared)).as_posix(),
                "sha256": sha256_file(shard_path),
                "byte_count": shard_path.stat().st_size,
                "source_count": len(shard_sources),
            }
        )

    combined = dict(value)
    combined["sources"] = sources
    combined["source_shard_receipts"] = shard_receipts
    return validate_manifest(combined)
