#!/usr/bin/env python3
"""Verify and safely materialize the C1 planning source bundle."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


class BundleError(RuntimeError):
    pass


PROTECTED_PATHS = {
    Path("README.md"),
    Path("MANIFEST.json"),
    Path(".github/workflows/ci.yml"),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_archive(repo: Path, manifest_path: Path) -> bytes:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("encoding") != "base64":
        raise BundleError("unsupported bundle encoding")
    encoded: list[str] = []
    for part in manifest.get("parts", []):
        path = repo / part["path"]
        if not path.is_file():
            raise BundleError(f"missing bundle part: {path}")
        raw = path.read_bytes()
        if _sha256(raw) != part["sha256"]:
            raise BundleError(f"bundle part hash mismatch: {path}")
        encoded.append(raw.decode("ascii"))
    try:
        archive = base64.b64decode("".join(encoded), validate=True)
    except Exception as exc:
        raise BundleError("invalid base64 bundle") from exc
    if len(archive) != manifest["archive_bytes"]:
        raise BundleError("archive size mismatch")
    if _sha256(archive) != manifest["archive_sha256"]:
        raise BundleError("archive hash mismatch")
    return archive


def validate_members(archive: bytes) -> list[tarfile.TarInfo]:
    try:
        tf = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz")
    except tarfile.TarError as exc:
        raise BundleError("invalid tar archive") from exc
    with tf:
        members = tf.getmembers()
        for member in members:
            name = member.name.removeprefix("./")
            path = PurePosixPath(name)
            if not name or name == ".":
                continue
            if path.is_absolute() or ".." in path.parts or path.parts[0] == ".git":
                raise BundleError(f"unsafe archive path: {member.name}")
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise BundleError(f"unsafe archive member type: {member.name}")
        return members


def materialize(repo: Path, manifest_path: Path, replace: bool, dry_run: bool) -> dict[str, object]:
    archive = load_archive(repo, manifest_path)
    members = validate_members(archive)
    files = [m for m in members if m.isfile()]
    if dry_run:
        return {"ok": True, "files": len(files), "archive_sha256": _sha256(archive), "dry_run": True}

    with tempfile.TemporaryDirectory(prefix="marketos-c1-") as td:
        stage = Path(td)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            tf.extractall(stage, members=members, filter="data")
        for source in sorted(stage.rglob("*")):
            rel = source.relative_to(stage)
            if rel == Path(".") or not source.is_file() or rel in PROTECTED_PATHS:
                continue
            target = repo / rel
            if target.exists() and not replace:
                raise BundleError(f"target exists; use --replace: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".materialize.tmp")
            shutil.copyfile(source, tmp)
            os.replace(tmp, target)
    return {"ok": True, "files": len(files), "archive_sha256": _sha256(archive), "dry_run": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--manifest", default="bundles/C1-plan-source.transport.json")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = Path(args.root).resolve()
    try:
        result = materialize(repo, repo / args.manifest, args.replace, args.dry_run)
    except BundleError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
