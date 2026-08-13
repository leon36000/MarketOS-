#!/usr/bin/env python3
"""Verify the Neon memory schema without import-time connections."""
from __future__ import annotations

import os
from typing import Any


def read_memory_state(database_url: str) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install requirements-neon.txt before verification") from exc

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM marketos_memory.requirements")
        requirements = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM marketos_memory.sources")
        sources = cur.fetchone()[0]
        cur.execute(
            """SELECT checkpoint_id,current_phase,live_trading_state,profitability_state
               FROM marketos_memory.checkpoints ORDER BY created_at DESC LIMIT 1"""
        )
        checkpoint = cur.fetchone()
    return {"requirements": requirements, "sources": sources, "latest_checkpoint": checkpoint}


def main() -> None:
    database_url = os.environ.get("NEON_DATABASE_URL")
    if not database_url:
        raise SystemExit("NEON_DATABASE_URL must be injected at runtime")
    print(read_memory_state(database_url))


if __name__ == "__main__":
    main()
