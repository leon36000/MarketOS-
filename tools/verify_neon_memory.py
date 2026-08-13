#!/usr/bin/env python3
from __future__ import annotations

import os
import psycopg

with psycopg.connect(os.environ["NEON_DATABASE_URL"]) as conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM marketos_memory.requirements")
    requirements = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM marketos_memory.sources")
    sources = cur.fetchone()[0]
    cur.execute(
        """SELECT checkpoint_id,current_phase,live_trading_state,profitability_state
           FROM marketos_memory.checkpoints ORDER BY created_at DESC LIMIT 1"""
    )
    checkpoint = cur.fetchone()
print({"requirements": requirements, "sources": sources, "latest_checkpoint": checkpoint})
