#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

IGNORED_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "htmlcov"}
IGNORED_FILES = {"MANIFEST.json", ".coverage", "coverage.xml", ".DS_Store"}


def _execution_contract_count(root: Path) -> int:
    return len(list((root / "execution-contracts").glob("*.md"))) + len(
        list((root / "planning" / "phases").glob("*/EXECUTION_CONTRACT.md"))
    )


def _manifest_entries(
    root: Path,
    content_overrides: Mapping[Path, bytes] | None = None,
) -> list[dict[str, Any]]:
    overrides = {path.resolve(): content for path, content in (content_overrides or {}).items()}
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if (
            path.name in IGNORED_FILES
            or path.suffix == ".pyc"
            or any(part in IGNORED_DIRS for part in relative.parts)
        ):
            continue
        content = overrides.get(path.resolve(), path.read_bytes())
        entries.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    return entries


def build_outputs(root: Path) -> dict[Path, str]:
    root = root.resolve()
    csv_path = root / "requirements" / "REQUIREMENT_CROSSWALK.csv"
    requirement_index_path = root / "requirements" / "REQUIREMENTS_INDEX.json"
    phase_index_path = root / "planning" / "PHASE_INDEX.json"

    requirement_index = json.loads(requirement_index_path.read_text(encoding="utf-8"))
    requirement_index["source_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    requirement_index_text = json.dumps(requirement_index, ensure_ascii=False, indent=2) + "\n"

    phase_index = json.loads(phase_index_path.read_text(encoding="utf-8"))
    phase_index["formal_execution_contracts_present"] = _execution_contract_count(root)
    phase_index_text = json.dumps(phase_index, ensure_ascii=False, indent=2) + "\n"

    overrides = {
        requirement_index_path: requirement_index_text.encode("utf-8"),
        phase_index_path: phase_index_text.encode("utf-8"),
    }
    manifest = {
        "version": "0.4.0",
        "files": _manifest_entries(root, content_overrides=overrides),
    }
    return {
        requirement_index_path: requirement_index_text,
        phase_index_path: phase_index_text,
        root / "MANIFEST.json": json.dumps(manifest, indent=2) + "\n",
    }


def regenerate(root: Path, check: bool = False) -> dict[str, Any]:
    root = root.resolve()
    outputs = build_outputs(root)
    changed: list[str] = []
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual != expected:
            changed.append(path.relative_to(root).as_posix())
            if not check:
                path.write_text(expected, encoding="utf-8")
    return {"ok": not changed if check else True, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = regenerate(Path(args.root), check=args.check)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else ("PASS" if report["ok"] else "STALE"))
    if not args.json:
        for path in report["changed"]:
            print(path)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
