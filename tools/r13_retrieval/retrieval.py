"""Exact response-byte retrieval with private raw storage and fail-closed thresholds."""
from __future__ import annotations

import time
import urllib.error
from pathlib import Path
from typing import Any, Mapping

from .core import (
    DEFAULT_USER_AGENT,
    FetchResponse,
    Fetcher,
    RETRIEVAL_SCHEMA,
    RetrievalError,
    _domain,
    _domain_allowed,
    canonical_json_bytes,
    sha256_bytes,
)
from .http import _extension, _invoke_fetcher, _matches_content_type, default_fetch
from .manifest import validate_manifest


def fetch_sources(
    manifest_value: Mapping[str, Any],
    workspace: Path,
    captured_at: str,
    fetcher: Fetcher = default_fetch,
    *,
    timeout: float = 45.0,
    retries: int = 2,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    validate_manifest(manifest_value)
    if not isinstance(captured_at, str) or not captured_at.endswith("Z"):
        raise RetrievalError("captured_at must be an explicit UTC timestamp ending in Z")
    if retries < 0 or retries > 8:
        raise RetrievalError("retries must be between 0 and 8")
    workspace.mkdir(parents=True, exist_ok=True)
    raw_root = workspace / "private_raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    allowed_domains = [str(item).lower() for item in manifest_value["allowed_domains"]]
    receipts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for source_item in manifest_value["sources"]:
        item = dict(source_item)
        source_id = str(item["source_id"])
        last_error: Exception | None = None
        response: FetchResponse | None = None
        attempts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                response = _invoke_fetcher(
                    fetcher,
                    str(item["url"]),
                    timeout=timeout,
                    user_agent=user_agent,
                    max_bytes=int(item["max_bytes"]),
                )
                break
            except (
                OSError,
                TimeoutError,
                urllib.error.URLError,
                urllib.error.HTTPError,
                RetrievalError,
            ) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(min(0.25 * (2**attempt), 1.0))
        if response is None:
            failures.append(
                {
                    "source_id": source_id,
                    "url": item["url"],
                    "required": item["required"],
                    "attempts": attempts,
                    "error_type": type(last_error).__name__ if last_error else "UNKNOWN",
                    "error": str(last_error)[:1000] if last_error else "unknown retrieval failure",
                    "captured_at": captured_at,
                }
            )
            continue
        try:
            if response.status < 200 or response.status >= 300:
                raise RetrievalError(f"HTTP status {response.status}")
            final_domain = _domain(response.final_url)
            if not _domain_allowed(final_domain, allowed_domains):
                raise RetrievalError(
                    f"redirected to non-allowlisted domain: {response.final_url}"
                )
            if len(response.body) > int(item["max_bytes"]):
                raise RetrievalError(f"response exceeds max_bytes={item['max_bytes']}")
            if not response.body:
                raise RetrievalError("empty response body")
            if not _matches_content_type(
                response.content_type, item["expected_content_types"]
            ):
                raise RetrievalError(f"unexpected content type: {response.content_type}")
            extension = _extension(response.content_type, response.final_url)
            raw_path = raw_root / f"{source_id}{extension}"
            raw_path.write_bytes(response.body)
            receipts.append(
                {
                    "source_id": source_id,
                    "title": item["title"],
                    "summary": item.get("summary", ""),
                    "url": item["url"],
                    "final_url": response.final_url,
                    "category": item["category"],
                    "authority_class": item["authority_class"],
                    "rights_class": item["rights_class"],
                    "required": item["required"],
                    "status": response.status,
                    "content_type": response.content_type,
                    "byte_count": len(response.body),
                    "sha256": sha256_bytes(response.body),
                    "private_raw_path": raw_path.relative_to(workspace).as_posix(),
                    "response_headers": dict(sorted(response.headers.items())),
                    "retrieval_method": "DIRECT_HTTPS_GITHUB_ACTIONS",
                    "captured_at": captured_at,
                    "attempts": attempts,
                    "raw_bytes_shared": False,
                }
            )
        except RetrievalError as exc:
            failures.append(
                {
                    "source_id": source_id,
                    "url": item["url"],
                    "required": item["required"],
                    "attempts": attempts,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                    "captured_at": captured_at,
                }
            )

    receipts.sort(key=lambda item: item["source_id"])
    failures.sort(key=lambda item: item["source_id"])
    by_category: dict[str, int] = {}
    total_bytes = 0
    for receipt in receipts:
        category = str(receipt["category"])
        by_category[category] = by_category.get(category, 0) + 1
        total_bytes += int(receipt["byte_count"])
    summary = {
        "declared_sources": len(manifest_value["sources"]),
        "successful_sources": len(receipts),
        "failed_sources": len(failures),
        "successful_by_category": dict(sorted(by_category.items())),
        "total_retrieved_bytes": total_bytes,
        "retrieved_byte_verified_sources": len(receipts),
        "raw_bytes_shared": False,
    }
    result = {
        "schema_version": RETRIEVAL_SCHEMA,
        "classification": "PRIVATE_SOURCE_BYTES_WITH_SHARED_RECEIPTS_ONLY",
        "captured_at": captured_at,
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest_value)),
        "receipts": receipts,
        "failures": failures,
        "summary": summary,
        "thresholds": manifest_value["thresholds"],
        "hard_locks": manifest_value["hard_locks"],
    }

    required_failures = [failure for failure in failures if failure["required"]]
    threshold_errors: list[str] = []
    thresholds = manifest_value["thresholds"]
    if len(receipts) < int(thresholds["minimum_successes"]):
        threshold_errors.append(
            f"successful_sources={len(receipts)} below minimum={thresholds['minimum_successes']}"
        )
    for category, minimum in thresholds["minimum_by_category"].items():
        observed = by_category.get(str(category), 0)
        if observed < int(minimum):
            threshold_errors.append(f"{category}={observed} below minimum={minimum}")
    if required_failures or threshold_errors:
        diagnostic_path = workspace / "FAILED_RETRIEVAL_STATE.json"
        diagnostic_path.write_bytes(
            canonical_json_bytes(result | {"threshold_errors": threshold_errors})
        )
        messages = [
            *(
                f"required source failed: {failure['source_id']}: {failure['error']}"
                for failure in required_failures
            ),
            *threshold_errors,
        ]
        raise RetrievalError("; ".join(messages))
    state_path = workspace / "PRIVATE_RETRIEVAL_STATE.json"
    state_path.write_bytes(canonical_json_bytes(result))
    return result


def _shared_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    value.pop("private_raw_path", None)
    value["raw_bytes_location"] = "PRIVATE_WORKSPACE_NOT_DISTRIBUTED"
    return value
