from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools.materialize_c1_bundle import BundleError, load_archive, materialize, validate_members

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "bundles/C1-plan-source.transport.json"


def test_real_bundle_dry_run() -> None:
    result = materialize(ROOT, MANIFEST, replace=False, dry_run=True)
    assert result["ok"] is True
    assert result["files"] >= 30


def _archive(member_name: str, payload: bytes = b"x") -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return out.getvalue()


@pytest.mark.parametrize("name", ["../escape", "/absolute", ".git/config"])
def test_unsafe_paths_are_rejected(name: str) -> None:
    with pytest.raises(BundleError):
        validate_members(_archive(name))


def test_symlink_is_rejected() -> None:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    with pytest.raises(BundleError):
        validate_members(out.getvalue())


def test_part_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bundles").mkdir()
    part = tmp_path / "bundles/part"
    part.write_text(base64.b64encode(b"abc").decode())
    manifest = {
        "encoding": "base64",
        "archive_bytes": 3,
        "archive_sha256": hashlib.sha256(b"abc").hexdigest(),
        "parts": [{"path": "bundles/part", "sha256": "0" * 64}],
    }
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        load_archive(tmp_path, mp)
