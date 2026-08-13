#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_IDS = {"AUD-DAT-001","AUD-DAT-002","AUD-DAT-003","AUD-DAT-010","AUD-DAT-011","AUD-SOC-003"}


def validate(root: Path) -> dict:
    errors = []
    decisions = json.loads((root / "planning/phases/C2/C2_DECISIONS.json").read_text())
    closure = json.loads((root / "planning/phases/C2/C2_REQUIREMENT_CLOSURE.json").read_text())
    locks = decisions.get("locks", {})
    expected = {
        "live_trading":"HARD_LOCKED",
        "profitability":"UNPROVEN",
        "provider_adopted":False,
        "purchase_authorized":False,
        "real_data_qualified":False,
        "unknown_rights_default":"DENY",
        "symbol_as_primary_key":"FORBIDDEN",
        "delisted_record_deletion":"FORBIDDEN",
        "silent_history_rewrite":"FORBIDDEN"
    }
    for key, value in expected.items():
        if locks.get(key) != value:
            errors.append(f"invalid lock: {key}")
    rules = decisions.get("identity_rules", {})
    if rules.get("primary_identity") != "MARKETOS_INTERNAL_UUID":
        errors.append("stable internal identity required")
    if rules.get("all_entities_bitemporal") is not True:
        errors.append("bitemporal identity required")
    if rules.get("inactive_and_delisted") != "RETAIN_FOREVER_IN_HISTORICAL_NAMESPACE":
        errors.append("inactive history must be retained")
    actions = decisions.get("corporate_action_rules", {})
    if actions.get("raw_events_append_only") is not True:
        errors.append("append-only events required")
    if actions.get("future_event_visibility") != "FORBIDDEN":
        errors.append("future event visibility forbidden")
    if actions.get("conflicts") != "QUARANTINE_UNTIL_RESOLVED":
        errors.append("conflicts must be quarantined")
    if any(item.get("status") == "ADOPTED" for item in decisions.get("candidate_sources", [])):
        errors.append("source adoption forbidden in C2")
    observed = {item.get("id") for item in closure.get("requirements", [])}
    if observed != REQUIRED_IDS:
        errors.append("requirement mapping mismatch")
    boundary = closure.get("hard_boundary", {})
    for key in ("provider_adopted","purchase_authorized","written_licences_obtained","real_data_qualified"):
        if boundary.get(key) is not False:
            errors.append(f"external gate must remain false: {key}")
    return {"ok":not errors,"errors":errors,"requirements":len(observed),"sources":len(decisions.get("candidate_sources", []))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate(Path(args.root))
    print(json.dumps(report, indent=2) if args.json else ("PASS" if report["ok"] else "FAIL"))
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
