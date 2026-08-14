#!/usr/bin/env python3
from pathlib import Path

path = Path(".github/data-foundation-temporal-hardening.py")
text = path.read_text(encoding="utf-8")
old = '''    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one patch site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
'''
new = '''    count = text.count(old)
    if count == 0:
        if new in text:
            return
        raise SystemExit(f"expected patch site in {path}, found 0")
    if count not in {1, 2}:
        raise SystemExit(f"expected one or two patch sites in {path}, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")
'''
if text.count(old) != 1:
    raise SystemExit("could not locate replace_once implementation")
text = text.replace(old, new, 1)
manifest_old = '''        if not isinstance(records, list):
            raise InvariantViolation("INVALID_DATASET_COMMIT_MANIFEST")
'''
manifest_new = '''        if not isinstance(records, (list, tuple)):
            raise InvariantViolation("INVALID_DATASET_COMMIT_MANIFEST")
'''
if text.count(manifest_old) != 1:
    raise SystemExit("could not locate committed-file record type check")
path.write_text(text.replace(manifest_old, manifest_new, 1), encoding="utf-8")
