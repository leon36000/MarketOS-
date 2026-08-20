#!/usr/bin/env python3
"""Build and verify a deterministic, offline MARKET-OS handoff pack."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


BUILDER_VERSION = "1.0.0"
PACK_FORMAT_VERSION = "1.0.0"
ZIP_MIN_EPOCH = 315532800
FORBIDDEN_PATH_NAMES = {".env", ".coverage", "coverage.xml", "id_rsa", "id_ed25519"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("OpenAI-style key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("credentialed PostgreSQL URL", re.compile(rb"postgres(?:ql)?://[^\s/:]+:[^\s/@]+@")),
)


class PackError(RuntimeError):
    """Raised when source or archive violates the pack contract."""


def _run(command: list[str], *, cwd: Path, check: bool = True, text: bool = True):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    source_path = str(cwd / "src")
    env["PYTHONPATH"] = source_path + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise PackError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(root: Path, *args: str) -> str:
    return _run(["git", *args], cwd=root).stdout.strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise PackError(f"unsafe archive path: {name!r}")
    if "\\" in name or name.startswith("/"):
        raise PackError(f"unsafe archive path: {name!r}")
    return path


def _secret_scan(relative: str, data: bytes) -> None:
    path = PurePosixPath(relative)
    if path.name.lower() in FORBIDDEN_PATH_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise PackError(f"forbidden secret-like path: {relative}")
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise PackError(f"possible {label} found in tracked file: {relative}")


def _tracked_files(root: Path) -> list[tuple[str, int]]:
    result = _run(["git", "ls-files", "--stage", "-z"], cwd=root, text=False)
    raw = result.stdout
    if not isinstance(raw, bytes):
        raise PackError("git ls-files did not return bytes")
    entries: list[tuple[str, int]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, encoded_path = record.partition(b"\t")
        if not separator:
            raise PackError(f"unexpected git index record: {record!r}")
        try:
            mode = int(metadata.split(maxsplit=1)[0], 8)
            relative = encoded_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PackError(f"invalid git index record: {record!r}") from exc
        _safe_name(relative)
        if mode == 0o120000:
            raise PackError(f"symlinks are forbidden: {relative}")
        if mode == 0o160000:
            raise PackError(f"submodules are forbidden: {relative}")
        if not (root / relative).is_file():
            raise PackError(f"tracked file missing from worktree: {relative}")
        entries.append((relative, mode))
    return sorted(entries)


def _git_info(root: Path) -> dict[str, Any]:
    remotes = _git(root, "remote")
    commit = _git(root, "rev-parse", "HEAD")
    commit_epoch = int(_git(root, "show", "-s", "--format=%ct", "HEAD"))
    source_epoch = int(os.environ.get("SOURCE_DATE_EPOCH", str(commit_epoch)))
    if source_epoch < 0:
        raise PackError("SOURCE_DATE_EPOCH must be non-negative")
    return {
        "repository": _git(root, "remote", "get-url", "origin") if remotes else "NOASSERTION",
        "commit": commit,
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "source_date_epoch": source_epoch,
    }


def _assert_clean(root: Path) -> None:
    output = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if output:
        raise PackError(f"source repository is not clean:\n{output}")


def _validated_output_path(root: Path, output: Path) -> Path:
    """Return a confined release path suitable for archive and sidecars."""
    root = root.resolve()
    candidate = output if output.is_absolute() else Path.cwd() / output
    if candidate.name in {"", ".", ".."} or candidate.suffix.lower() != ".zip":
        raise PackError("pack output must be a .zip file path")
    if candidate.is_symlink():
        raise PackError("pack output symlinks are forbidden")

    temp_root = Path(tempfile.gettempdir()).resolve()
    parent = candidate.parent.resolve()
    try:
        parent.relative_to(temp_root)
    except ValueError as exc:
        raise PackError("pack output must be under the system temporary directory") from exc

    validated = parent / candidate.name
    if validated == root or root in validated.parents:
        raise PackError("pack output must be outside the source repository")
    if validated.is_symlink():
        raise PackError("pack output symlinks are forbidden")
    if validated.exists() and not validated.is_file():
        raise PackError("pack output must not replace a non-file")
    return validated


def _sidecar_path(output: Path, suffix: str) -> Path:
    if suffix not in {".sha256", ".verification.json"}:
        raise PackError("unsupported pack sidecar")
    temp_root = Path(tempfile.gettempdir()).resolve()
    parent = output.parent.resolve()
    try:
        parent.relative_to(temp_root)
    except ValueError as exc:
        raise PackError("pack sidecar must be under the system temporary directory") from exc
    return parent / f"{output.name}{suffix}"


def _write_sidecar(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise PackError(f"pack sidecar symlinks are forbidden: {path.name}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise PackError(f"could not write pack sidecar: {path.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _run_json_validator(root: Path, relative: str) -> dict[str, Any]:
    result = _run([sys.executable, relative, "--root", ".", "--json"], cwd=root)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PackError(f"validator did not return JSON: {relative}\n{result.stdout}") from exc
    if not report.get("ok"):
        raise PackError(f"validator failed: {relative}\n{json.dumps(report, indent=2)}")
    return report


def validate_source(root: Path, *, require_clean: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if require_clean:
        _assert_clean(root)
    reports = {
        "repository": _run_json_validator(root, "tools/validate_repository.py"),
        "requirements_boundary": _run_json_validator(root, "tools/verify_requirements_reconciliation.py"),
        "proof_engine": _run_json_validator(root, "tools/verify_proof_engine.py"),
    }
    return reports


def _iso(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _zip_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    moment = dt.datetime.fromtimestamp(max(epoch, ZIP_MIN_EPOCH), tz=dt.timezone.utc)
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second - moment.second % 2)


def _read_first(commit: str) -> bytes:
    return (
        "# MARKET-OS — Read First\n\n"
        "This is a verified design/build handoff, not completed trading software.\n\n"
        "```yaml\n"
        "software_implementation_complete: false\n"
        "strategy_edge_proven: false\n"
        "profitability: UNPROVEN\n"
        "live_trading: HARD_LOCKED\n"
        f"source_commit: {commit}\n"
        "```\n\n"
        "Run validators only from a trusted checkout after verifying this pack.\n"
        "Never execute validators or any other code extracted from this pack;\n"
        "archive verification is structural-only. The pack cannot\n"
        "select providers, authorize capital, enable live trading or prove\n"
        "profitability.\n"
    ).encode("utf-8")


def _provenance(info: dict[str, Any], reports: dict[str, Any] | None) -> bytes:
    return _canonical_json(
        {
            "format_version": PACK_FORMAT_VERSION,
            "builder": "tools/build_claude_pack.py",
            "builder_version": BUILDER_VERSION,
            "repository": info["repository"],
            "commit": info["commit"],
            "tree": info["tree"],
            "source_date_epoch": info["source_date_epoch"],
            "created": _iso(info["source_date_epoch"]),
            "python": sys.version.split()[0],
            "zlib": zlib.ZLIB_VERSION,
            "design_boundary": {
                "software_implementation_complete": False,
                "strategy_edge_proven": False,
                "profitability": "UNPROVEN",
                "live_trading": "HARD_LOCKED",
            },
            "source_validator_reports": reports or "NOT_RUN_BY_LIBRARY_CALL",
        }
    )


def _spdx(info: dict[str, Any], repository_files: dict[str, bytes]) -> bytes:
    package_id = "SPDXRef-Package-MARKET-OS-Design"
    files: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = [
        {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": package_id}
    ]
    for index, (name, data) in enumerate(sorted(repository_files.items()), start=1):
        file_id = f"SPDXRef-File-{index:04d}-{_sha256(data)[:12]}"
        files.append(
            {
                "SPDXID": file_id,
                "fileName": f"repository/{name}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(data)}],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {"spdxElementId": package_id, "relationshipType": "CONTAINS", "relatedSpdxElement": file_id}
        )
    digest_set = "".join(sorted(_sha256(data) for data in repository_files.values())).encode("ascii")
    return _canonical_json(
        {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "MARKET-OS Design Handoff",
            "documentNamespace": f"https://marketos.local/spdx/{info['commit']}/{info['tree']}",
            "creationInfo": {
                "created": _iso(info["source_date_epoch"]),
                "creators": [f"Tool: MARKET-OS-pack-builder-{BUILDER_VERSION}"],
            },
            "packages": [
                {
                    "SPDXID": package_id,
                    "name": "MARKET-OS Design Plan",
                    "versionInfo": info["commit"],
                    "downloadLocation": info["repository"],
                    "filesAnalyzed": True,
                    "licenseConcluded": "NOASSERTION",
                    "licenseDeclared": "NOASSERTION",
                    "copyrightText": "NOASSERTION",
                    "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(digest_set)}],
                }
            ],
            "files": files,
            "relationships": relationships,
        }
    )


def _members(root: Path, tracked: Iterable[tuple[str, int]], info: dict[str, Any], reports: dict[str, Any] | None) -> tuple[dict[str, bytes], dict[str, int]]:
    repository_files: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    for relative, mode in tracked:
        data = (root / relative).read_bytes()
        _secret_scan(relative, data)
        repository_files[relative] = data
        modes[f"repository/{relative}"] = 0o755 if mode & 0o111 else 0o644

    members: dict[str, bytes] = {
        "READ_FIRST.md": _read_first(info["commit"]),
        "PACK_PROVENANCE.json": _provenance(info, reports),
        "PACK_SBOM.spdx.json": _spdx(info, repository_files),
    }
    members.update({f"repository/{name}": data for name, data in repository_files.items()})
    for name in members:
        modes.setdefault(name, 0o644)
    manifest = {
        "format_version": PACK_FORMAT_VERSION,
        "source_commit": info["commit"],
        "source_tree": info["tree"],
        "file_count_excluding_manifest": len(members),
        "files": [
            {"path": name, "bytes": len(data), "sha256": _sha256(data)}
            for name, data in sorted(members.items())
        ],
    }
    members["PACK_MANIFEST.json"] = _canonical_json(manifest)
    modes["PACK_MANIFEST.json"] = 0o644
    return members, modes


def _write_zip(output: Path, members: dict[str, bytes], modes: dict[str, int], epoch: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _zip_time(epoch)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(members):
                _safe_name(name)
                info = zipfile.ZipInfo(name, date_time=timestamp)
                info.create_system = 3
                info.external_attr = ((stat.S_IFREG | modes.get(name, 0o644)) << 16)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.flag_bits |= 0x800
                archive.writestr(info, members[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, output)
    except OSError as exc:
        raise PackError(f"could not write pack archive: {output.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def build_pack(root: Path, output: Path, *, validate: bool = True, require_clean: bool = True) -> dict[str, Any]:
    root = root.resolve()
    output = _validated_output_path(root, output)
    if require_clean:
        _assert_clean(root)
    reports = validate_source(root, require_clean=require_clean) if validate else None
    info = _git_info(root)
    tracked = _tracked_files(root)
    members, modes = _members(root, tracked, info, reports)
    _write_zip(output, members, modes, info["source_date_epoch"])
    return {
        "archive": str(output),
        "archive_sha256": _sha256(output.read_bytes()),
        "manifest_sha256": _sha256(members["PACK_MANIFEST.json"]),
        "member_count": len(members),
        "tracked_file_count": len(tracked),
        "commit": info["commit"],
        "tree": info["tree"],
        "source_date_epoch": info["source_date_epoch"],
        "source_validator_reports": reports,
    }


def verify_archive(archive_path: Path, *, run_repository_checks: bool = False) -> dict[str, Any]:
    """Verify archive structure and hashes without executing archive contents.

    ``run_repository_checks`` remains as a compatibility argument for callers
    that used the old API. It is intentionally ignored: validators extracted
    from an untrusted archive must never be executed. Source validators run
    before packaging in :func:`build_pack`.
    """
    archive_path = archive_path.resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise PackError("archive contains duplicate member names")
        for info in infos:
            _safe_name(info.filename)
            if ((info.external_attr >> 16) & 0o170000) == stat.S_IFLNK:
                raise PackError(f"archive contains symlink: {info.filename}")
            if info.is_dir():
                raise PackError(f"archive contains unexpected directory entry: {info.filename}")
        try:
            manifest_bytes = archive.read("PACK_MANIFEST.json")
            manifest = json.loads(manifest_bytes)
        except (KeyError, json.JSONDecodeError) as exc:
            raise PackError("PACK_MANIFEST.json missing or invalid") from exc
        expected = {item["path"]: item for item in manifest.get("files", [])}
        actual = set(names) - {"PACK_MANIFEST.json"}
        if set(expected) != actual:
            raise PackError(
                "pack manifest/member set mismatch: "
                f"missing={sorted(actual - set(expected))}, extra={sorted(set(expected) - actual)}"
            )
        for name, item in expected.items():
            data = archive.read(name)
            if len(data) != item.get("bytes"):
                raise PackError(f"pack byte-count mismatch: {name}")
            if _sha256(data) != item.get("sha256"):
                raise PackError(f"pack hash mismatch: {name}")

    return {
        "ok": True,
        "archive_sha256": _sha256(archive_path.read_bytes()),
        "manifest_sha256": _sha256(manifest_bytes),
        "member_count": len(names),
        "source_commit": manifest.get("source_commit"),
        "verification_mode": "structural-only",
        "requested_repository_checks": bool(run_repository_checks),
        "validator_reports": "NOT_RUN_ON_UNTRUSTED_ARCHIVE",
    }


def build_and_verify(root: Path, output: Path, *, require_clean: bool = True) -> dict[str, Any]:
    root = root.resolve()
    output = _validated_output_path(root, output)
    first = build_pack(root, output, validate=True, require_clean=require_clean)
    verification = verify_archive(output, run_repository_checks=False)
    with tempfile.TemporaryDirectory(prefix="marketos-pack-rebuild-") as temp_dir:
        second_path = Path(temp_dir) / output.name
        second = build_pack(root, second_path, validate=True, require_clean=require_clean)
        if first["archive_sha256"] != second["archive_sha256"]:
            raise PackError(
                "deterministic rebuild mismatch: "
                f"first={first['archive_sha256']} second={second['archive_sha256']}"
            )
    report = {
        "ok": True,
        "builder_version": BUILDER_VERSION,
        "build": first,
        "verification": verification,
        "deterministic_rebuild_match": True,
    }
    _write_sidecar(
        _sidecar_path(output, ".sha256"),
        f"{first['archive_sha256']}  {output.name}\n".encode("utf-8"),
    )
    _write_sidecar(_sidecar_path(output, ".verification.json"), _canonical_json(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = (
            build_and_verify(Path(args.root), Path(args.output), require_clean=not args.allow_dirty)
            if args.verify
            else build_pack(Path(args.root), Path(args.output), validate=True, require_clean=not args.allow_dirty)
        )
    except PackError as exc:
        failure = {"ok": False, "error": str(exc)}
        print(json.dumps(failure, indent=2) if args.json else f"FAIL: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else "PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
