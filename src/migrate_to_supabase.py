"""One-time migration: pushes the existing local data/profile.json and
data/log.csv into Supabase. Run once after setting SUPABASE_URL/SUPABASE_KEY
in .env and creating the tables via supabase_schema.sql.

Run with: python src/migrate_to_supabase.py
"""

import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    profile_path = DATA_DIR / "profile.json"
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile.pop("age", None)  # computed field, not stored
        sb.table("profile").upsert({"id": 1, "data": profile}).execute()
        print(f"[migrate] profile migrated ({len(profile)} top-level fields)")
    else:
        print("[migrate] no local profile.json found, skipping")

    log_path = DATA_DIR / "log.csv"
    if log_path.exists():
        with log_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        entries = [
            {
                "entry_date": r["date"],
                "weight_kg": float(r["weight_kg"]) if r.get("weight_kg") else None,
                "calories": float(r["calories"]) if r.get("calories") else None,
                "protein_g": float(r["protein_g"]) if r.get("protein_g") else None,
                "workout": r.get("workout") or "",
                "notes": r.get("notes") or "",
            }
            for r in rows
        ]
        if entries:
            sb.table("logs").insert(entries).execute()
        print(f"[migrate] {len(entries)} log entries migrated")
    else:
        print("[migrate] no local log.csv found, skipping")


if __name__ == "__main__":
    main()
