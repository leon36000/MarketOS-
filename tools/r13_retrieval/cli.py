"""CLI orchestration for R13 source-content retrieval."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

from .bundle import _write_json, build_receipt_bundle
from .core import RUN_SCHEMA, RetrievalError, sha256_file
from .manifest import load_manifest
from .retrieval import fetch_sources


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args(argv)

    manifest_value = load_manifest(args.manifest)
    output_root: Path = args.output_root
    private_root = output_root / "private"
    shared_root = output_root / "shared"
    if output_root.exists():
        shutil.rmtree(output_root)
    private_root.mkdir(parents=True)
    shared_root.mkdir(parents=True)
    retrieval = fetch_sources(
        manifest_value,
        private_root,
        args.captured_at,
        timeout=args.timeout,
        retries=args.retries,
    )
    bundle_name = "MarketOS_R13_Source_Content_Retrieval_Addendum_v1.zip"
    first = build_receipt_bundle(
        retrieval,
        shared_root / "receipt_tree",
        shared_root / bundle_name,
    )
    with tempfile.TemporaryDirectory() as td:
        second_path = Path(td) / bundle_name
        second = build_receipt_bundle(retrieval, Path(td) / "receipt_tree", second_path)
        if (
            first["bundle_sha256"] != second["bundle_sha256"]
            or first["bundle_path"].read_bytes() != second_path.read_bytes()
        ):
            raise RetrievalError("deterministic rebuild mismatch")
    run_receipt = {
        "schema_version": RUN_SCHEMA,
        "classification": "PREPHASE_SOURCE_CONTENT_ADDENDUM_NOT_PHASE_CLOSURE",
        "captured_at": args.captured_at,
        "manifest_path": args.manifest.as_posix(),
        "manifest_sha256": retrieval["manifest_sha256"],
        "retrieval_summary": retrieval["summary"],
        "retrieval_failures": retrieval["failures"],
        "bundle": {
            "name": first["bundle_path"].name,
            "sha256": first["bundle_sha256"],
            "byte_count": first["bundle_byte_count"],
            "sidecar_name": first["sidecar_path"].name,
            "sidecar_sha256": first["sidecar_sha256"],
        },
        "verification": first["validation"]
        | {
            "deterministic_rebuild": "PASS_BYTE_IDENTICAL",
            "source_hashes_verified_against_private_bytes": True,
        },
        "epistemic_limits": {
            "raw_bytes_shared": False,
            "redistribution_right_asserted": False,
            "ai_ml_training_right_asserted": False,
            "technology_adoptions": 0,
            "phase_event_appended": False,
            "implementation_started": False,
        },
        "hard_locks": retrieval["hard_locks"],
    }
    receipt_path = (
        shared_root / "MarketOS_R13_Source_Content_Retrieval_Addendum_v1_Receipt.json"
    )
    _write_json(receipt_path, run_receipt)
    receipt_sha = sha256_file(receipt_path)
    Path(str(receipt_path) + ".sha256").write_text(
        f"{receipt_sha}  {receipt_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(run_receipt, indent=2, sort_keys=True))
    return 0
