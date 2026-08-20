# C16 pack builder boundary

`tools/build_claude_pack.py` creates a deterministic ZIP handoff from tracked
Git files only. It records the source commit/tree, source-date epoch, file
hashes, byte counts, provenance and an SPDX 2.3 design-package document.

The builder rejects dirty sources, unsafe paths, symlinks, submodules,
credential-like files and hash/member mismatches. `--verify` validates the
source before packaging, builds twice, compares archive bytes and performs
structural/hash verification without executing any code extracted from the
archive. The repository, requirements-boundary, Proof Binding and Proof Engine
validators run only against the trusted source tree. The Proof Binding ledger
pins authority artifacts and PR/CI receipts but does not promote partial
C13–C15 evidence.

This is an integration gate, not a claim that the software is complete. The
pack explicitly retains:

```yaml
software_implementation_complete: false
strategy_edge_proven: false
profitability: UNPROVEN
live_trading: HARD_LOCKED
```

The final C16 pack still depends on Claude Code delivering verified C13–C15
contracts and their gates. Until then, a pack can be technically reproducible
while remaining an incomplete implementation handoff.

```bash
python tools/build_claude_pack.py \
  --root . \
  --output /tmp/MARKET-OS-CODEX-PACK.zip \
  --verify \
  --json
```
