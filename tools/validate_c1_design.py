#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_ARTIFACTS = [
    "planning/phases/C1/C1_DECISIONS.json",
    "planning/phases/C1/C1_REQUIREMENT_CLOSURE.json",
    "docs/architecture/C1_SERVICE_TOPOLOGY.md",
    "docs/architecture/C1_DEPLOYMENT_PROFILES.md",
    "docs/architecture/C1_SECRETS_IDENTITY.md",
    "docs/architecture/C1_BACKUP_RESTORE_DR.md",
    "docs/architecture/C1_ALERTING_NOTIFICATIONS.md",
    "docs/architecture/C1_OBSERVABILITY_CONTRACT.md",
    "docs/research/C1_APP_MATRIX.md",
]
REQUIRED_REQUIREMENTS = {
    "AUD-CMP-008", "AUD-CMP-009", "AUD-CMP-010", "AUD-CMP-011",
    "AUD-CMP-013", "AUD-CMP-014", "AUD-UI-006", "AUD-UI-007",
    "AUD-UI-009", "AUD-FIN-004", "AUD-FIN-005",
}


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing C1 artifact: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"expected JSON object: {path}")
        return {}
    return data


def validate_c1_design(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    for relative in REQUIRED_ARTIFACTS:
        if not (root / relative).is_file():
            errors.append(f"missing C1 artifact: {relative}")

    decisions = _load_json(root / "planning/phases/C1/C1_DECISIONS.json", errors)
    closure = _load_json(root / "planning/phases/C1/C1_REQUIREMENT_CLOSURE.json", errors)
    if decisions.get("phase") != "C1":
        errors.append("C1 decisions must declare phase C1")

    locks = decisions.get("locks", {})
    expected_locks = {
        "live_trading": "HARD_LOCKED",
        "profitability": "UNPROVEN",
        "public_ingress_default": "FORBIDDEN",
        "plaintext_secrets": "FORBIDDEN",
        "mutable_image_tags": "FORBIDDEN",
        "kubernetes_required": False,
    }
    for key, expected in expected_locks.items():
        if locks.get(key) != expected:
            errors.append(f"C1 lock {key} must be {expected!r}")

    contracts = decisions.get("architecture_contracts", {})
    expected_contracts = {
        "standalone_runtime": "ROOTLESS_PODMAN_QUADLET",
        "cluster_runtime": "K3S_OPTIONAL_AFTER_PARITY_GATE",
        "telemetry_protocol": "OPENTELEMETRY_OTLP",
        "alert_router": "PROMETHEUS_ALERTMANAGER",
        "backup_authority": "RESTORE_DRILL_RECEIPT",
    }
    for key, expected in expected_contracts.items():
        if contracts.get(key) != expected:
            errors.append(f"C1 architecture contract {key} must be {expected}")

    profiles = decisions.get("deployment_profiles", [])
    if not isinstance(profiles, list):
        errors.append("deployment_profiles must be a list")
        profiles = []
    profile_ids = [p.get("profile_id") for p in profiles if isinstance(p, dict)]
    if len(set(profile_ids)) != len(profile_ids):
        errors.append("duplicate C1 deployment profile IDs")
    standalone = next((p for p in profiles if p.get("profile_id") == "standalone-core"), None)
    if not standalone or standalone.get("mandatory") is not True:
        errors.append("standalone-core must be the mandatory deployment profile")
    if standalone and standalone.get("runtime") != "rootless-podman-quadlet":
        errors.append("standalone-core must use rootless Podman Quadlet")
    cluster = next((p for p in profiles if p.get("profile_id") == "cluster-k3s"), None)
    if not cluster or cluster.get("mandatory") is not False:
        errors.append("cluster-k3s must remain optional")
    for profile in profiles:
        if profile.get("public_ingress") is not False:
            errors.append(f"deployment profile allows public ingress: {profile.get('profile_id')}")

    tiers = decisions.get("secret_tiers", [])
    required_tiers = {"S0_BOOTSTRAP", "S1_STANDALONE_RUNTIME", "S2_DISTRIBUTED"}
    observed_tiers = {tier.get("tier") for tier in tiers if isinstance(tier, dict)}
    if observed_tiers != required_tiers:
        errors.append(f"C1 secret tiers must be exactly {sorted(required_tiers)}")
    for tier in tiers:
        if tier.get("browser_readback") is not False:
            errors.append(f"secret browser readback must be false: {tier.get('tier')}")

    candidates = decisions.get("application_candidates", [])
    candidate_ids = [item.get("id") for item in candidates if isinstance(item, dict)]
    if len(set(candidate_ids)) != len(candidate_ids):
        errors.append("duplicate C1 application candidate IDs")
    if any(item.get("status") == "ADOPTED" for item in candidates if isinstance(item, dict)):
        errors.append("C1 may not globally ADOPT an application candidate")
    portainer = next((item for item in candidates if item.get("id") == "portainer"), None)
    if not portainer or portainer.get("status") != "REJECTED_FOR_ROOTLESS_BASELINE":
        errors.append("Portainer must not be selected for the rootless baseline")

    observability = decisions.get("observability_rules", {})
    expected_chain = ["source_data", "dataset", "feature", "model", "decision", "risk", "order", "fill", "reconciliation", "outcome"]
    if observability.get("correlation_chain") != expected_chain:
        errors.append("C1 observability correlation chain is incomplete or reordered")
    if observability.get("alloy_otel_engine") != "FORBIDDEN_EXPERIMENTAL_BASELINE":
        errors.append("experimental Alloy OTel engine must be excluded from the baseline")
    if observability.get("secret_redaction") is not True or observability.get("bounded_cardinality") is not True:
        errors.append("C1 observability must require redaction and bounded cardinality")

    alerting = decisions.get("alerting_rules", {})
    if alerting.get("delivery_semantics") != "AT_LEAST_ONCE":
        errors.append("C1 alerting must model at-least-once delivery")
    for key in ("receiver_idempotency_required", "deduplication_required", "runbook_required"):
        if alerting.get(key) is not True:
            errors.append(f"C1 alerting must require {key}")
    if alerting.get("mobile_sensitive_actions") != "FORBIDDEN":
        errors.append("sensitive mobile actions must remain forbidden")

    backup = decisions.get("backup_rules", {})
    for key in ("encrypted", "append_only_writer_separate_from_prune_admin", "repository_check_required", "clean_host_restore_required", "hash_comparison_required"):
        if backup.get(key) is not True:
            errors.append(f"C1 backup rule must require {key}")
    if backup.get("backup_without_restore_status") != "UNVERIFIED":
        errors.append("backup without restore must remain UNVERIFIED")

    records = closure.get("requirements", [])
    observed_requirements = {record.get("id") for record in records if isinstance(record, dict)}
    if observed_requirements != REQUIRED_REQUIREMENTS:
        errors.append(f"C1 requirement closure mismatch: missing={sorted(REQUIRED_REQUIREMENTS - observed_requirements)}, extra={sorted(observed_requirements - REQUIRED_REQUIREMENTS)}")
    for record in records:
        for artifact in record.get("artifacts", []):
            if not (root / artifact).is_file():
                errors.append(f"C1 requirement references missing artifact: {record.get('id')} -> {artifact}")
    boundary = closure.get("hard_boundary", {})
    if boundary.get("software_implemented") is not False or boundary.get("target_nodes_qualified") is not False:
        errors.append("C1 design must keep implementation and target qualification open")
    if boundary.get("live_trading") != "HARD_LOCKED" or boundary.get("profitability") != "UNPROVEN":
        errors.append("C1 hard boundary must preserve live/profitability locks")

    return {"ok": not errors, "errors": errors, "phase": decisions.get("phase"), "profile_count": len(profiles), "candidate_count": len(candidates), "requirement_count": len(observed_requirements)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_c1_design(Path(args.root))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "FAIL"))
    if not args.json:
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
