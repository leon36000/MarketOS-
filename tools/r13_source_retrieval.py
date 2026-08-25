#!/usr/bin/env python3
"""Compatibility API and CLI entry point for R13 source-content retrieval."""
from __future__ import annotations

import sys

from tools.r13_retrieval import *  # noqa: F401,F403
from tools.r13_retrieval.cli import run_cli
from tools.r13_retrieval.core import ManifestError, RetrievalError

if __name__ == "__main__":
    try:
        raise SystemExit(run_cli())
    except (ManifestError, RetrievalError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
