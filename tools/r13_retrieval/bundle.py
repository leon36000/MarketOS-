"""Deterministic receipt-only ZIP construction and verification."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .core import (
    BUNDLE_SCHEMA,
    FAIL_CLOSED_RIGHTS,
    FIXED_ZIP_DT,
    REQUIRED_BUNDLE_FILES,
    RETRIEVAL_SCHEMA,
    SHA256_RE,
    RetrievalError,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .retrieval import _shared_receipt


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _zip_directory(directory: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            rel = path.relative_to(directory).as_posix()
            info = zipfile.ZipInfo(rel, FIXED_ZIP_DT)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def build_receipt_bundle(
    retrieval: Mapping[str, Any],
    shared_root: Path,
    bundle_path: Path,
) -> dict[str, Any]:
    if retrieval.get("schema_version") != RETRIEVAL_SCHEMA:
        raise RetrievalError("invalid retrieval schema")
    if shared_root.exists():
        shutil.rmtree(shared_root)
    shared_root.mkdir(parents=True, exist_ok=True)

    shared_receipts = [_shared_receipt(item) for item in retrieval["receipts"]]
    rights_matrix = [
        {
            "source_id": item["source_id"],
            "url": item["url"],
            "authority_class": item["authority_class"],
            "rights_class": item["rights_class"],
            "retrieval_allowed_for_hashing": True,
            "redistribution_right_asserted": False,
            "ai_ml_training_right_asserted": False,
            "raw_bytes_shared": False,
            "legal_review_required": True,
        }
        for item in shared_receipts
    ]
    _write_json(
        shared_root / "SOURCE_CONTENT_RECEIPTS.json",
        {
            "schema_version": "marketos.r13-source-content-receipts.v1",
            "captured_at": retrieval["captured_at"],
            "manifest_sha256": retrieval["manifest_sha256"],
            "receipts": shared_receipts,
        },
    )
    _write_json(
        shared_root / "SOURCE_RIGHTS_MATRIX.json",
        {
            "schema_version": "marketos.r13-source-rights-matrix.v1",
            "policy": FAIL_CLOSED_RIGHTS,
            "entries": rights_matrix,
        },
    )
    _write_json(
        shared_root / "RETRIEVAL_FAILURES.json",
        {
            "schema_version": "marketos.r13-source-retrieval-failures.v1",
            "failures": retrieval["failures"],
        },
    )
    _write_json(
        shared_root / "SOURCE_RETRIEVAL_SUMMARY.json",
        {
            "schema_version": BUNDLE_SCHEMA,
            "classification": "RECEIPT_ONLY_NO_RAW_SOURCE_BYTES",
            "captured_at": retrieval["captured_at"],
            "summary": retrieval["summary"],
            "thresholds": retrieval["thresholds"],
            "hard_locks": retrieval["hard_locks"],
            "epistemic_effect": {
                "locator_only_sources_reduced": True,
                "retrieved_content_hashes_added": len(shared_receipts),
                "original_publisher_byte_authority": "DIRECT_HTTPS_RESPONSE_BYTES",
                "redistribution_or_training_rights": "NOT_ASSERTED",
                "phase_event_appended": False,
                "technology_adoptions": 0,
            },
        },
    )
    readme = f"""# MarketOS R13 Source-Content Retrieval Addendum

Classification: `RECEIPT_ONLY_NO_RAW_SOURCE_BYTES`

This package records direct HTTPS response hashes and provenance for {len(shared_receipts)} official or primary sources. Raw response bytes remain in a private CI workspace and are deliberately absent from this ZIP. Retrieval does not assert redistribution, model-training, or commercial-use rights.

- Captured at: `{retrieval['captured_at']}`
- Verified source responses: `{len(shared_receipts)}`
- Failed optional or required responses: `{len(retrieval['failures'])}`
- Total privately retrieved bytes: `{retrieval['summary']['total_retrieved_bytes']}`
- Technology adoptions: `0`
- R13 phase event appended: `false`
- `live_trading`: `HARD_LOCKED`
- `profitability`: `UNPROVEN`

The receipts are research inputs and bakeoff evidence. They do not select a technology or close R13.
"""
    (shared_root / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    entries = []
    for path in sorted(p for p in shared_root.rglob("*") if p.is_file()):
        entries.append(
            {
                "path": path.relative_to(shared_root).as_posix(),
                "byte_count": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema_version": "marketos.deterministic-bundle-manifest.v1",
        "classification": "RECEIPT_ONLY_NO_RAW_SOURCE_BYTES",
        "entries": entries,
        "raw_source_bytes_in_bundle": False,
        "created_at": retrieval["captured_at"],
    }
    _write_json(shared_root / "BUNDLE_MANIFEST.json", manifest)
    _zip_directory(shared_root, bundle_path)
    validation = validate_receipt_bundle(bundle_path)
    bundle_sha = sha256_file(bundle_path)
    sidecar_path = Path(str(bundle_path) + ".sha256")
    sidecar_path.write_text(
        f"{bundle_sha}  {bundle_path.name}\n", encoding="utf-8", newline="\n"
    )
    return {
        "bundle_path": bundle_path,
        "bundle_sha256": bundle_sha,
        "bundle_byte_count": bundle_path.stat().st_size,
        "sidecar_path": sidecar_path,
        "sidecar_sha256": sha256_file(sidecar_path),
        "validation": validation,
    }


def validate_receipt_bundle(bundle_path: Path) -> dict[str, Any]:
    if not bundle_path.is_file():
        raise RetrievalError(f"bundle not found: {bundle_path}")
    with zipfile.ZipFile(bundle_path) as archive:
        bad = archive.testzip()
        if bad:
            raise RetrievalError(f"ZIP CRC failure: {bad}")
        names = archive.namelist()
        if names != sorted(names):
            raise RetrievalError("ZIP entries are not sorted")
        if len(names) != len(set(names)):
            raise RetrievalError("ZIP contains duplicate entries")
        if any(
            name.startswith(("private_raw/", "raw_sources/", "sources_raw/"))
            or "/private_raw/" in name
            for name in names
        ):
            raise RetrievalError("bundle contains private raw source bytes")
        missing = REQUIRED_BUNDLE_FILES - set(names)
        if missing:
            raise RetrievalError(f"bundle missing required files: {sorted(missing)}")
        for name in names:
            if name.endswith(".json"):
                try:
                    json.loads(archive.read(name).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RetrievalError(f"invalid JSON in {name}: {exc}") from exc
        receipt_doc = json.loads(archive.read("SOURCE_CONTENT_RECEIPTS.json"))
        rights_doc = json.loads(archive.read("SOURCE_RIGHTS_MATRIX.json"))
        summary_doc = json.loads(archive.read("SOURCE_RETRIEVAL_SUMMARY.json"))
        receipts = receipt_doc.get("receipts", [])
        if not receipts:
            raise RetrievalError("bundle contains no successful receipts")
        for receipt in receipts:
            if not SHA256_RE.fullmatch(str(receipt.get("sha256", ""))):
                raise RetrievalError(
                    f"malformed source hash for {receipt.get('source_id')}"
                )
            if receipt.get("raw_bytes_shared") is not False:
                raise RetrievalError(
                    f"raw byte sharing not false for {receipt.get('source_id')}"
                )
            if receipt.get("rights_class") != FAIL_CLOSED_RIGHTS:
                raise RetrievalError(
                    f"rights not fail-closed for {receipt.get('source_id')}"
                )
            if "private_raw_path" in receipt:
                raise RetrievalError("private raw path leaked into shared receipt")
        if len(rights_doc.get("entries", [])) != len(receipts):
            raise RetrievalError("rights matrix count differs from receipt count")
        if summary_doc.get("classification") != "RECEIPT_ONLY_NO_RAW_SOURCE_BYTES":
            raise RetrievalError("summary classification is invalid")
        bundle_manifest = json.loads(archive.read("BUNDLE_MANIFEST.json"))
        if bundle_manifest.get("raw_source_bytes_in_bundle") is not False:
            raise RetrievalError("bundle manifest raw-source flag is invalid")
        for entry in bundle_manifest.get("entries", []):
            name = entry["path"]
            data = archive.read(name)
            if len(data) != entry["byte_count"] or sha256_bytes(data) != entry["sha256"]:
                raise RetrievalError(f"bundle manifest mismatch for {name}")
    return {
        "status": "PASS",
        "zip_integrity": "PASS",
        "json_parse": "PASS",
        "raw_source_bytes_absent": True,
        "entry_count": len(names),
        "receipt_count": len(receipts),
    }
