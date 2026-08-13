#!/usr/bin/env python3
"""Ingest reconciled requirements into Neon without import-time side effects."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_PATH = ROOT / "requirements" / "REQUIREMENT_CROSSWALK.csv"


def authority(status: str) -> str:
    if status == "LOCKED_CANON":
        return "VERIFIED_CANON"
    if "USER_REQUIREMENT" in status or "OWNER_REQUIREMENT" in status:
        return "DIRECT_OWNER_REQUIREMENT"
    return "AUDIT_RECONCILED"


def requirement_record(row: dict[str, str]) -> tuple[Any, ...]:
    text = row["requirement"]
    phase = row["closure_phase"].strip()
    phases = [] if phase in ("", "—") else [phase]
    return (
        row["id"], text, authority(row["coverage_status"]),
        row["coverage_status"], "MARKET-OS", phases,
        hashlib.sha256(text.encode()).hexdigest(),
        json.dumps({
            "category": row["category"],
            "evidence": row["evidence"],
            "remaining_gap": row["remaining_gap"],
        }),
    )


def main() -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install requirements-neon.txt before running ingestion") from exc

    database_url = os.environ.get("NEON_DATABASE_URL")
    if not database_url:
        raise SystemExit("NEON_DATABASE_URL must be injected at runtime")
    csv_path = Path(os.getenv("MARKETOS_REQUIREMENTS_CSV", DEFAULT_CSV_PATH))

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur, csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
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
                    requirement_record(row),
                )
        conn.commit()
    print("requirements ingested")


if __name__ == "__main__":
    main()
