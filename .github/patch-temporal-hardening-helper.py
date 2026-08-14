#!/usr/bin/env python3
from pathlib import Path

patch_path = Path(".github/data-foundation-temporal-hardening.py")
patch_text = patch_path.read_text(encoding="utf-8")

helper_old = '''    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one patch site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
'''
helper_new = '''    count = text.count(old)
    if count == 0:
        if new in text:
            return
        raise SystemExit(f"expected patch site in {path}, found 0")
    if count not in {1, 2}:
        raise SystemExit(f"expected one or two patch sites in {path}, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")
'''
if patch_text.count(helper_old) != 1:
    raise SystemExit("could not locate replace_once implementation")
patch_text = patch_text.replace(helper_old, helper_new, 1)

manifest_old = "if not isinstance(records, list):"
manifest_new = "if not isinstance(records, (list, tuple)):"
if patch_text.count(manifest_old) != 1:
    raise SystemExit(
        "could not locate committed-file record type check: "
        f"{patch_text.count(manifest_old)}"
    )
patch_path.write_text(
    patch_text.replace(manifest_old, manifest_new, 1),
    encoding="utf-8",
)

# Keep the tampered member the same byte length as the original so this test
# isolates SHA-256 verification from the separate byte-count diagnostic.
test_path = Path("tests/test_data_foundation_temporal_semantics.py")
test_text = test_path.read_text(encoding="utf-8")
test_old = '(result.commit_path.parent / "part-000.jsonl").write_bytes(b"tampered")'
test_new = '(result.commit_path.parent / "part-000.jsonl").write_bytes(b\'{"id":2}\\n\')'
if test_text.count(test_old) != 1:
    raise SystemExit(
        f"could not locate dataset corruption fixture: {test_text.count(test_old)}"
    )
test_path.write_text(test_text.replace(test_old, test_new, 1), encoding="utf-8")
