#!/usr/bin/env python3
"""Ingest reconciled requirements into Neon; read the URL only from the environment."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = Path(os.getenv("MARKETOS_REQUIREMENTS_CSV", ROOT / "requirements" / "REQUIREMENT_CROSSWALK.csv"))
DATABASE_URL = os.environ["NEON_DATABASE_URL"]


def authority(status: str) -> str:
    if status == "LOCKED_CANON":
        return "VERIFIED_CANON"
    if "USER_REQUIREMENT" in status or "OWNER_REQUIREMENT" in status:
        return "DIRECT_OWNER_REQUIREMENT"
    return "AUDIT_RECONCILED"


def main() -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur, CSV_PATH.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                text = row["requirement"]
                phase = row["closure_phase"].strip()
                phases = [] if phase in ("", "—") else [phase]
                cur.execute(
                    """
                    INSERT INTO marketos_memory.requirements
                    (requirement_id,text,authority,status,owner,phase_targets,sha256,metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (requirement_id) DO UPDATE SET
                      text=EXCLUDED.text, authority=EXCLUDED.authority,
                      status=EXCLUDED.status, phase_targets=EXCLUDED.phase_targets,
                      sha256=EXCLUDED.sha256, metadata=EXCLUDED.metadata
                    """,
                    (
                        row["id"], text, authority(row["coverage_status"]),
                        row["coverage_status"], "MARKET-OS", phases,
                        hashlib.sha256(text.encode()).hexdigest(),
                        json.dumps({
                            "category": row["category"],
                            "evidence": row["evidence"],
                            "remaining_gap": row["remaining_gap"],
                        }),
                    ),
                )
        conn.commit()
    print("requirements ingested")


if __name__ == "__main__":
    main()
