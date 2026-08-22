# C16 — Build Pack Acceptance

## Layout

```text
READ_FIRST.md
PACK_MANIFEST.json
PACK_PROVENANCE.json
PACK_SBOM.spdx.json
repository/
```

`repository/` contains only Git-tracked files from the verified commit. Root metadata is generated and cannot become an unmanifested repository file.

## Required properties

- sorted deterministic ZIP entries and timestamps derived from `SOURCE_DATE_EPOCH`/commit time;
- SHA-256 for every included file and the final archive;
- Git repository URL, commit ID, tree ID and dirty-state check;
- SPDX document describing the design package;
- no `.git`, caches, coverage files, environment files, private keys, credentials, runtime datasets or model weights;
- no symlink traversal or absolute paths;
- exact live/profitability/software-completion boundaries in `READ_FIRST.md`;
- extraction into an empty directory;
- manifest and byte-count verification;
- offline execution of repository and C16 validators from the extracted `repository/` directory;
- repeat build from the same commit produces identical archive SHA-256.

## Failure conditions

Untracked source, dirty repository, unsafe path, secret-like file, hash mismatch, duplicate entry, missing validator, non-deterministic rebuild, strengthened financial claim or extracted validation failure blocks release.

## Release boundary

The archive is a design/build handoff. It cannot enable a broker, change limits, mark implementation nodes complete or authorize live trading.
