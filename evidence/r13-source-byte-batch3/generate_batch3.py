from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


BATCH_ID = "R13-PRIMARY-SOURCE-BYTES-BATCH-003"
BUNDLE_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Receipt_Only_2026-08-25.zip"
RECEIPT_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Receipt.json"
MANIFEST_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Manifest.json"
SOURCE_RECEIPTS_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Source_Receipts.jsonl"
VERIFICATION_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Verification_Log.txt"
README_NAME = "README.md"
HASH_INDEX_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Hash_Index.json"
STATUS_NAME = "MarketOS_R13_Primary_Source_Byte_Batch_003_Status.json"

SEMANTIC_HEAD_SHA256 = "08ff66fb5f630a654d624f4b85927834fbbdeeb71b5c17891d3691513cc181a9"
R13_BOOTSTRAP_SNAPSHOT_ID = "1ed9c62f-c68f-4a2d-9c1c-c056703a821d"
R13_BOOTSTRAP_SNAPSHOT_SHA256 = "e241796dbfc59ef9d7e0f451bb7157fef6c7829900742260af5e00071fa264d9"
R12_TRANSITION_CHECKPOINT_ID = "12121212-1212-4212-8212-121212121234"
PARENT_SOURCE_BATCH_CHECKPOINT = "13131313-1313-4313-8313-131313131308"
PARALLEL_BAKEOFF_CHECKPOINT = "13131313-1313-4313-8313-131313131307"
COUNT_AUTHORITY_DECISION_SHA256 = "ee8b1255194ad44eb0b324e8d2125e8072e7ce4a486e23cb7dc7196d75bab73c"

OBSERVED_BEFORE = 16
PLANNING_TARGET = 30
EXPECTED_BATCH_COUNT = 14

HARD_LOCKS = {
    "live_trading": "HARD_LOCKED",
    "profitability": "UNPROVEN",
    "false_done": "FORBIDDEN",
    "stubs": "FORBIDDEN",
    "project_complete": False,
    "production_ready": False,
}

RIGHTS_POLICY = {
    "raw_bytes_shared": False,
    "redistribution_right_asserted": False,
    "ai_ml_training_right_asserted": False,
    "unknown_or_project_specific_rights": "DENY_FAIL_CLOSED",
    "legal_review_required_before_redistribution_or_training": True,
}

PRIOR_SOURCE_SHA256S = frozenset(
    {
        "3365069d76e8820628da2cc5de815bec16b44c0bd23ff7294111cd9c0ab2fb8a",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
        "9efe6c6bb2894b238f69e3478f7ed96b26276e5687d9e93b991ee3cd0a2ab97d",
        "8fa8528066d69dd031993e53ef816f5e04ce74ee7a4271ab894ba28f7dec143f",
        "4be08a194b9c970bf9309ac19f09e7deaecb763957091bf08298bf0e897e7eab",
        "6aadde8e3e213220587dd72272361f62a45e897f06a1753bf7a9db4c2b86ac0d",
        "780282389332ef7d5a6aaf21f99626c4aa15006d78784125911ab68a3edb311d",
        "30058538ee88d58aef86afe6069528a9da2261f2bdc1dc46bf6cd00abac1369b",
        "d12f55865fecc773406d67e18cca65f9520ffa34f1bcab0116d8be8337a248d2",
        "d5c106c18a8a501d6fc538ace0d96279e14da0ebc0c06833135d2ec1354a936f",
        "09da968ee07242fb057a2e0315104f2c2af32ef0231701167c1d87aca907382b",
        "ecb78395389558e0a1c8a95fed8a023193832ecc9cabd48aa58fe4114da78893",
        "e041bc7885569636f6a2c0d43a4eb7ff3d67315f05d4858619570a56e74aefa8",
        "a5f0318b8af4d5dc211ea686a0ea39528f00379fab2af6a755e17d6241081160",
        "a2b0e92dd36ef0ce3638eb7655fa4d556e05341053201bb780531ed488d2f9c2",
        "3cfe4aef30372149cf4311fee414fa356627a116aa6a3d1dd1a2fa01f642b5f5",
    }
)


@dataclass(frozen=True)
class SourceSpec:
    id: str
    repo: str
    commit: str
    path: str
    role: str
    license_evidence_id: str
    license_evidence_sha256: str


SKLEARN_COMMIT = "a456b324bc68cf86ef4394f36debe83d829fb124"
DOUBLEML_COMMIT = "1808b07a13cc8c61f508c1ed6aec658ea32a2807"
GRF_COMMIT = "5bee99b51471f76cb2d63acbc8a9b0ffec408ba0"

SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        "sklearn_model_selection_public_api",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "sklearn/model_selection/__init__.py",
        "MODEL_SELECTION_PUBLIC_API_AND_SPLITTER_INVENTORY",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "sklearn_cv_indices_example",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "examples/model_selection/plot_cv_indices.py",
        "GROUP_STRATIFICATION_AND_CROSS_VALIDATION_SPLIT_VISUALIZATION",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "sklearn_cv_predict_example",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "examples/model_selection/plot_cv_predict.py",
        "OUT_OF_FOLD_PREDICTION_AND_DECOMPOSABILITY_LIMITATIONS",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "sklearn_nested_cv_example",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "examples/model_selection/plot_nested_cross_validation_iris.py",
        "NESTED_CROSS_VALIDATION_MODEL_SELECTION_BIAS",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "sklearn_permutation_test_example",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "examples/model_selection/plot_permutation_tests_for_classification.py",
        "PERMUTATION_TEST_SCORE_SIGNIFICANCE",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "sklearn_train_test_error_example",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "examples/model_selection/plot_train_error_vs_test_error.py",
        "TRAIN_TEST_GENERALIZATION_GAP",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "sklearn_underfit_overfit_example",
        "scikit-learn/scikit-learn",
        SKLEARN_COMMIT,
        "examples/model_selection/plot_underfitting_overfitting.py",
        "BIAS_VARIANCE_UNDERFITTING_AND_OVERFITTING",
        "scikit_learn_copying",
        "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    ),
    SourceSpec(
        "doubleml_architecture_doc",
        "DoubleML/doubleml-for-py",
        DOUBLEML_COMMIT,
        "doc/diagrams/architecture.md",
        "DOUBLE_MACHINE_LEARNING_ARCHITECTURE",
        "doubleml_license",
        "6aadde8e3e213220587dd72272361f62a45e897f06a1753bf7a9db4c2b86ac0d",
    ),
    SourceSpec(
        "doubleml_testing_structure_doc",
        "DoubleML/doubleml-for-py",
        DOUBLEML_COMMIT,
        "doc/diagrams/testing_structure.md",
        "DOUBLE_MACHINE_LEARNING_TEST_STRUCTURE",
        "doubleml_license",
        "6aadde8e3e213220587dd72272361f62a45e897f06a1753bf7a9db4c2b86ac0d",
    ),
    SourceSpec(
        "doubleml_api_index",
        "DoubleML/doubleml-for-py",
        DOUBLEML_COMMIT,
        "doc/index.rst",
        "DOUBLE_MACHINE_LEARNING_API_IDENTITY",
        "doubleml_license",
        "6aadde8e3e213220587dd72272361f62a45e897f06a1753bf7a9db4c2b86ac0d",
    ),
    SourceSpec(
        "grf_causal_forest_contract",
        "grf-labs/grf",
        GRF_COMMIT,
        "r-package/grf/man/causal_forest.Rd",
        "HONEST_CAUSAL_FOREST_HETEROGENEOUS_TREATMENT_EFFECT_CONTRACT",
        "grf_notice",
        "780282389332ef7d5a6aaf21f99626c4aa15006d78784125911ab68a3edb311d",
    ),
    SourceSpec(
        "grf_regression_forest_contract",
        "grf-labs/grf",
        GRF_COMMIT,
        "r-package/grf/man/regression_forest.Rd",
        "REGRESSION_FOREST_BASELINE_CONTRACT",
        "grf_notice",
        "780282389332ef7d5a6aaf21f99626c4aa15006d78784125911ab68a3edb311d",
    ),
    SourceSpec(
        "grf_instrumental_forest_contract",
        "grf-labs/grf",
        GRF_COMMIT,
        "r-package/grf/man/instrumental_forest.Rd",
        "INSTRUMENTAL_VARIABLE_HETEROGENEOUS_EFFECT_CONTRACT",
        "grf_notice",
        "780282389332ef7d5a6aaf21f99626c4aa15006d78784125911ab68a3edb311d",
    ),
    SourceSpec(
        "grf_multi_arm_causal_forest_contract",
        "grf-labs/grf",
        GRF_COMMIT,
        "r-package/grf/man/multi_arm_causal_forest.Rd",
        "MULTI_TREATMENT_CAUSAL_FOREST_CONTRACT",
        "grf_notice",
        "780282389332ef7d5a6aaf21f99626c4aa15006d78784125911ab68a3edb311d",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _request_json(url: str, token: str, attempts: int = 4) -> Mapping[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MarketOS-R13-source-byte-batch-003",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read()
            decoded = json.loads(body.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError(f"Expected JSON object from {url}")
            return decoded
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"GitHub request failed for {url}: {last_error}")


def fetch_source(spec: SourceSpec, token: str, retrieved_at: str) -> dict[str, Any]:
    quoted_path = urllib.parse.quote(spec.path, safe="/")
    quoted_ref = urllib.parse.quote(spec.commit, safe="")
    api_url = f"https://api.github.com/repos/{spec.repo}/contents/{quoted_path}?ref={quoted_ref}"
    metadata = _request_json(api_url, token)

    if metadata.get("type") != "file":
        raise ValueError(f"Expected file for {spec.repo}:{spec.path}")
    if metadata.get("encoding") != "base64":
        raise ValueError(f"Expected base64 content for {spec.repo}:{spec.path}")
    content_value = metadata.get("content")
    if not isinstance(content_value, str):
        raise ValueError(f"Missing base64 content for {spec.repo}:{spec.path}")

    try:
        data = base64.b64decode(content_value, validate=True)
    except ValueError as exc:
        raise ValueError(f"Invalid base64 for {spec.repo}:{spec.path}") from exc

    source = {
        **asdict(spec),
        "expected_git_blob_sha1": metadata.get("sha"),
        "metadata_size": metadata.get("size"),
        "api_url": api_url,
        "download_url": metadata.get("download_url"),
        "html_url": metadata.get("html_url"),
        "data": data,
    }
    return build_source_receipt(source, retrieved_at=retrieved_at)


def build_source_receipt(source: Mapping[str, Any], retrieved_at: str) -> dict[str, Any]:
    data_value = source.get("data")
    if not isinstance(data_value, bytes):
        raise ValueError("Source data must be bytes")
    data = data_value

    expected_size = source.get("metadata_size")
    if not isinstance(expected_size, int) or expected_size != len(data):
        raise ValueError(
            f"Metadata size mismatch for {source.get('repo')}:{source.get('path')}: "
            f"metadata={expected_size} actual={len(data)}"
        )

    expected_blob = source.get("expected_git_blob_sha1")
    computed_blob = git_blob_sha1(data)
    if expected_blob != computed_blob:
        raise ValueError(
            f"Git blob SHA-1 mismatch for {source.get('repo')}:{source.get('path')}: "
            f"expected={expected_blob} actual={computed_blob}"
        )

    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Source is not UTF-8: {source.get('repo')}:{source.get('path')}") from exc

    receipt = {
        "id": source.get("id"),
        "repo": source.get("repo"),
        "commit": source.get("commit"),
        "path": source.get("path"),
        "role": source.get("role"),
        "license_evidence_id": source.get("license_evidence_id"),
        "license_evidence_sha256": source.get("license_evidence_sha256"),
        "api_url": source.get("api_url"),
        "download_url": source.get("download_url"),
        "html_url": source.get("html_url"),
        "canonical_raw_url": (
            f"https://raw.githubusercontent.com/{source.get('repo')}/"
            f"{source.get('commit')}/{source.get('path')}"
        ),
        "git_blob_sha1": expected_blob,
        "computed_git_blob_sha1": computed_blob,
        "git_blob_match": True,
        "sha256": sha256_hex(data),
        "byte_count": len(data),
        "content_type": "text/plain; charset=utf-8",
        "utf8_valid": True,
        "retrieval_method": "GITHUB_CONTENTS_API_BASE64_AT_PINNED_COMMIT",
        "retrieved_at": retrieved_at,
        "source_class": "OFFICIAL_VERSIONED_GITHUB_REPOSITORY_FILE",
        "raw_bytes_stored_runner_private": True,
        "raw_bytes_shared": False,
        "redistribution_right_asserted": False,
        "ai_ml_training_right_asserted": False,
        "rights_status": "FAIL_CLOSED_PENDING_PROJECT_SPECIFIC_LEGAL_REVIEW",
        "authority": "EXACT_BYTE_RECEIPT_WITH_GIT_BLOB_AND_SHA256",
    }
    return receipt


def validate_receipts(receipts: Sequence[Mapping[str, Any]]) -> None:
    if len(receipts) != EXPECTED_BATCH_COUNT:
        raise ValueError(f"Expected {EXPECTED_BATCH_COUNT} receipts, got {len(receipts)}")

    logical_keys = {(r["repo"], r["commit"], r["path"]) for r in receipts}
    source_ids = {r["id"] for r in receipts}
    sha256s = {r["sha256"] for r in receipts}
    blob_sha1s = {r["git_blob_sha1"] for r in receipts}
    if len(logical_keys) != EXPECTED_BATCH_COUNT:
        raise ValueError("Duplicate repo/commit/path in batch")
    if len(source_ids) != EXPECTED_BATCH_COUNT:
        raise ValueError("Duplicate source ID in batch")
    if len(sha256s) != EXPECTED_BATCH_COUNT:
        raise ValueError("Duplicate SHA-256 in batch")
    if len(blob_sha1s) != EXPECTED_BATCH_COUNT:
        raise ValueError("Duplicate Git blob identity in batch")
    overlap = sha256s & PRIOR_SOURCE_SHA256S
    if overlap:
        raise ValueError(f"Batch duplicates prior source SHA-256 values: {sorted(overlap)}")
    if not all(r.get("utf8_valid") is True for r in receipts):
        raise ValueError("At least one source is not valid UTF-8")
    if not all(r.get("git_blob_match") is True for r in receipts):
        raise ValueError("At least one Git blob identity did not match")
    if any(r.get("raw_bytes_shared") is not False for r in receipts):
        raise ValueError("Raw source bytes may not be shared")
    if any(r.get("redistribution_right_asserted") is not False for r in receipts):
        raise ValueError("Redistribution rights may not be asserted")
    if any(r.get("ai_ml_training_right_asserted") is not False for r in receipts):
        raise ValueError("AI/ML-training rights may not be asserted")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_sidecar(path: Path) -> Path:
    digest = sha256_hex(path.read_bytes())
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return sidecar


def build_deterministic_zip(input_dir: Path, output_path: Path) -> None:
    files = sorted(
        (path for path in input_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(input_dir).as_posix(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source in files:
            relative = source.relative_to(input_dir).as_posix()
            info = zipfile.ZipInfo(relative)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.create_system = 3
            archive.writestr(
                info,
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def build_status(
    receipts: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
    *,
    created_at: str | None = None,
    receipt: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    hash_index: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verified = len(receipts)
    after = OBSERVED_BEFORE + verified
    return {
        "schema_version": "marketos.r13-primary-source-byte-batch-status.v1",
        "batch_id": BATCH_ID,
        "status": "PASS_RECEIPT_ONLY_BATCH_VERIFIED",
        "created_at": created_at or utc_now(),
        "bundle": {
            "name": bundle.get("name", BUNDLE_NAME),
            "sha256": bundle["sha256"],
            "byte_count": bundle["byte_count"],
            "zip_integrity": bundle.get("zip_integrity", "PASS"),
            "deterministic_rebuild": bundle.get(
                "deterministic_rebuild", "PASS_BYTE_IDENTICAL"
            ),
            "raw_source_bytes_in_bundle": False,
        },
        "receipt": dict(receipt or {}),
        "manifest": dict(manifest or {}),
        "hash_index": dict(hash_index or {}),
        "retrieval": {
            "observed_before": OBSERVED_BEFORE,
            "verified_in_batch": verified,
            "authoritative_observed_after": after,
            "planning_target": PLANNING_TARGET,
            "remaining": max(0, PLANNING_TARGET - after),
            "target_achieved": after >= PLANNING_TARGET,
            "batch_bytes": sum(int(r.get("byte_count", 0)) for r in receipts),
        },
        "verification": {
            "all_utf8": all(r.get("utf8_valid") is True for r in receipts),
            "all_git_blob_sha1_match": all(
                r.get("git_blob_match") is True for r in receipts
            ),
            "all_sha256_well_formed": all(
                isinstance(r.get("sha256"), str) and len(r["sha256"]) == 64
                for r in receipts
            ),
            "unique_repo_commit_path": len(
                {(r["repo"], r["commit"], r["path"]) for r in receipts}
            )
            == verified,
            "unique_sha256": len({r["sha256"] for r in receipts}) == verified,
            "raw_bytes_excluded_from_receipt_bundle": True,
        },
        "rights_policy": dict(RIGHTS_POLICY),
        "r13_phase_event_appended": False,
        "r13_snapshot_mutated": False,
        "technology_adoptions": 0,
        "implementation": "NOT_STARTED_OUTSIDE_RESEARCH_LAB",
        "hard_locks": dict(HARD_LOCKS),
    }


def _file_receipt(path: Path) -> dict[str, Any]:
    return {"name": path.name, "sha256": sha256_hex(path.read_bytes()), "byte_count": path.stat().st_size}


def build_outputs(output_dir: Path, receipts: Sequence[Mapping[str, Any]], created_at: str) -> dict[str, Any]:
    validate_receipts(receipts)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    receipt_dir = output_dir / "receipt_bundle"
    receipt_dir.mkdir()

    total_bytes = sum(int(r["byte_count"]) for r in receipts)
    repositories = sorted({str(r["repo"]) for r in receipts})
    commits = sorted({(str(r["repo"]), str(r["commit"])) for r in receipts})

    receipt_value = {
        "schema_version": "marketos.r13-primary-source-byte-batch.v1",
        "batch_id": BATCH_ID,
        "classification": (
            "POST_R12_CHECKPOINT_R13_PRECLOSURE_SOURCE_BYTE_RECEIPT_"
            "NOT_PHASE_REVISION_NOT_SNAPSHOT_MEMBER"
        ),
        "created_at": created_at,
        "semantic_authority": {
            "phase_id": "R12",
            "phase_revision": 3,
            "phase_event_sha256": SEMANTIC_HEAD_SHA256,
            "r13_bootstrap_snapshot_id": R13_BOOTSTRAP_SNAPSHOT_ID,
            "r13_bootstrap_snapshot_sha256": R13_BOOTSTRAP_SNAPSHOT_SHA256,
            "r12_transition_checkpoint_id": R12_TRANSITION_CHECKPOINT_ID,
            "parent_source_batch_checkpoint": PARENT_SOURCE_BATCH_CHECKPOINT,
            "parallel_bakeoff_checkpoint": PARALLEL_BAKEOFF_CHECKPOINT,
            "r13_phase_event_appended": False,
        },
        "count_authority": {
            "decision_id": "D-R13-SOURCE-BYTE-COUNT-AUTHORITY",
            "decision_revision": 1,
            "decision_event_sha256": COUNT_AUTHORITY_DECISION_SHA256,
            "observed_before_batch": OBSERVED_BEFORE,
            "retrieved_byte_verified_sources_in_batch": EXPECTED_BATCH_COUNT,
            "authoritative_observed_after_batch": PLANNING_TARGET,
            "planning_target": PLANNING_TARGET,
            "target_achieved": True,
            "remaining_to_target": 0,
        },
        "retrieval_summary": {
            "documents": EXPECTED_BATCH_COUNT,
            "repositories": len(repositories),
            "repository_names": repositories,
            "commits": len(commits),
            "total_retrieved_bytes_in_batch": total_bytes,
            "cumulative_retrieved_sources": PLANNING_TARGET,
            "cumulative_retrieved_bytes": 18899 + total_bytes,
            "utf8_documents": EXPECTED_BATCH_COUNT,
            "git_blob_identity_matches": EXPECTED_BATCH_COUNT,
            "sha256_verified_documents": EXPECTED_BATCH_COUNT,
            "raw_bytes_in_shared_bundle": False,
        },
        "method_coverage": [
            "MODEL_SELECTION_SPLITTER_INVENTORY",
            "GROUP_AND_STRATIFIED_CROSS_VALIDATION",
            "OUT_OF_FOLD_PREDICTION_LIMITATIONS",
            "NESTED_CROSS_VALIDATION",
            "PERMUTATION_TESTS",
            "TRAIN_TEST_GENERALIZATION_GAP",
            "UNDERFITTING_AND_OVERFITTING",
            "DOUBLE_MACHINE_LEARNING_ARCHITECTURE_AND_TEST_STRUCTURE",
            "HONEST_CAUSAL_FORESTS",
            "REGRESSION_FORESTS",
            "INSTRUMENTAL_FORESTS",
            "MULTI_ARM_CAUSAL_FORESTS",
        ],
        "rights_policy": dict(RIGHTS_POLICY),
        "verification": {
            "all_utf8": True,
            "all_git_blob_sha1_match": True,
            "all_sha256_well_formed": True,
            "unique_repo_commit_path": True,
            "unique_sha256": True,
            "no_prior_batch_sha256_duplicates": True,
            "raw_bytes_excluded_from_receipt_bundle": True,
        },
        "sources": list(receipts),
        "open_state": {
            "open_loop_id": "OL-R13-PRIMARY-SOURCE-BYTES-RIGHTS",
            "status_after_batch": "IN_PROGRESS",
            "source_count_target_achieved": True,
            "rights_qualification_complete": False,
            "common_bakeoff_complete": False,
            "empirical_finance_gold_sets_complete": False,
            "r13_phase_promotion_authorized": False,
            "technology_adoptions": 0,
            "implementation": "NOT_STARTED_OUTSIDE_RESEARCH_LAB",
        },
        "hard_locks": dict(HARD_LOCKS),
    }

    manifest_value = {
        "schema_version": "marketos.receipt-only-manifest.v1",
        "batch_id": BATCH_ID,
        "created_at": created_at,
        "bundle_name": BUNDLE_NAME,
        "raw_source_bytes_in_bundle": False,
        "raw_source_bytes_persisted_by_workflow": False,
        "source_document_count": EXPECTED_BATCH_COUNT,
        "source_document_total_bytes": total_bytes,
        "cumulative_source_document_count": PLANNING_TARGET,
        "cumulative_total_retrieved_bytes": 18899 + total_bytes,
        "rights_policy": dict(RIGHTS_POLICY),
        "hard_locks": dict(HARD_LOCKS),
    }

    readme_text = f"""# MarketOS R13 — Primary Source Byte Batch 003

Receipt-only, post-R12-checkpoint R13 prephase evidence.

- Exact documents in this batch: {EXPECTED_BATCH_COUNT}
- Observed before: {OBSERVED_BEFORE}
- Observed after: {PLANNING_TARGET}
- Planning target reached: yes, for source-byte count only
- R13 phase promotion authorized: no
- Raw source bytes in this archive: no
- Raw source bytes persisted by workflow: no
- Redistribution right asserted: no
- AI/ML-training right asserted: no
- Rights policy: deny fail-closed
- Technology adopted: none
- Live trading: HARD_LOCKED
- Profitability: UNPROVEN
"""

    receipt_path = receipt_dir / RECEIPT_NAME
    manifest_path = receipt_dir / MANIFEST_NAME
    source_receipts_path = receipt_dir / SOURCE_RECEIPTS_NAME
    verification_path = receipt_dir / VERIFICATION_NAME
    readme_path = receipt_dir / README_NAME
    hash_index_path = receipt_dir / HASH_INDEX_NAME

    write_json(receipt_path, receipt_value)
    write_json(manifest_path, manifest_value)
    source_receipts_path.write_text(
        "".join(json.dumps(dict(r), sort_keys=True, ensure_ascii=False) + "\n" for r in receipts),
        encoding="utf-8",
    )
    verification_lines = [
        f"batch_id={BATCH_ID}",
        f"created_at={created_at}",
        f"document_count={EXPECTED_BATCH_COUNT}",
        f"batch_bytes={total_bytes}",
        f"observed_before={OBSERVED_BEFORE}",
        f"authoritative_observed_after={PLANNING_TARGET}",
        f"planning_target={PLANNING_TARGET}",
        "all_utf8=PASS",
        "all_git_blob_sha1_match=PASS",
        "all_sha256=PASS",
        "unique_repo_commit_path=PASS",
        "unique_sha256=PASS",
        "no_prior_batch_sha256_duplicates=PASS",
        "raw_bytes_in_shared_bundle=false",
        "raw_bytes_persisted_by_workflow=false",
        "redistribution_right_asserted=false",
        "ai_ml_training_right_asserted=false",
        "rights_policy=DENY_FAIL_CLOSED",
        "r13_phase_event_appended=false",
        "technology_adoptions=0",
    ]
    verification_lines.extend(
        f"{r['id']} bytes={r['byte_count']} sha256={r['sha256']} "
        f"git_blob_sha1={r['git_blob_sha1']} blob_match=PASS"
        for r in receipts
    )
    verification_path.write_text("\n".join(verification_lines) + "\n", encoding="utf-8")
    readme_path.write_text(readme_text, encoding="utf-8")

    core_paths = [receipt_path, manifest_path, source_receipts_path, verification_path, readme_path]
    hash_index_value = {
        "schema_version": "marketos.non-circular-hash-index.v1",
        "batch_id": BATCH_ID,
        "created_at": created_at,
        "self_excluded": True,
        "sidecars_excluded": True,
        "files": {path.name: _file_receipt(path) for path in core_paths},
    }
    write_json(hash_index_path, hash_index_value)
    core_paths.append(hash_index_path)

    for path in core_paths:
        write_sidecar(path)

    bundle_path = output_dir / BUNDLE_NAME
    rebuild_path = output_dir / f".{BUNDLE_NAME}.rebuild"
    build_deterministic_zip(receipt_dir, bundle_path)
    build_deterministic_zip(receipt_dir, rebuild_path)
    if bundle_path.read_bytes() != rebuild_path.read_bytes():
        raise ValueError("Deterministic ZIP rebuild mismatch")
    rebuild_path.unlink()

    with zipfile.ZipFile(bundle_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC verification failed")
        names = archive.namelist()
        if names != sorted(names):
            raise ValueError("ZIP member order is not deterministic")
        if any(name.startswith("raw/") for name in names):
            raise ValueError("Raw source bytes leaked into receipt-only bundle")

    bundle_value = {
        "name": BUNDLE_NAME,
        "sha256": sha256_hex(bundle_path.read_bytes()),
        "byte_count": bundle_path.stat().st_size,
        "zip_integrity": "PASS",
        "deterministic_rebuild": "PASS_BYTE_IDENTICAL",
    }
    write_sidecar(bundle_path)

    status_value = build_status(
        receipts,
        bundle_value,
        created_at=created_at,
        receipt=_file_receipt(receipt_path),
        manifest=_file_receipt(manifest_path),
        hash_index=_file_receipt(hash_index_path),
    )
    status_value["retrieval"]["cumulative_total_bytes"] = 18899 + total_bytes
    status_path = output_dir / STATUS_NAME
    write_json(status_path, status_value)
    write_sidecar(status_path)

    # Copy only receipt material from the private staging directory to the upload root.
    for path in receipt_dir.iterdir():
        shutil.copy2(path, output_dir / path.name)
    shutil.rmtree(receipt_dir)

    return status_value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build R13 primary source byte batch 003")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    created_at = utc_now()
    receipts = [fetch_source(spec, token, created_at) for spec in SOURCE_SPECS]
    status = build_outputs(args.output_dir, receipts, created_at)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
