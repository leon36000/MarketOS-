# C16 — Packaging and Provenance Contract

The pack is built from a clean Git commit. Tracked paths are the only repository inputs. Generated root metadata records repository URL, commit, tree, source-date epoch, builder version, validator results and archive hash.

The builder sorts paths, normalizes ZIP metadata and uses a fixed timestamp derived from the commit. The manifest excludes itself from recursive hashing but lists every other pack file with bytes and SHA-256. The archive hash is written beside the archive after closure.

SPDX metadata identifies MARKET-OS as a design package and lists the repository as its source. It is not a dependency-vulnerability assertion. SLSA and NIST SSDF concepts inform provenance, review and reproducibility, but no conformance level is claimed without an external build service and attestation chain.

The pack never includes credentials, provider responses containing secrets, licensed market data, model weights, `.git`, caches or transient test outputs. Memory access is configured by opaque references after installation.

Verification occurs twice: in the source tree and after extraction. A pack that cannot validate offline after extraction is rejected even when its ZIP opens successfully.
