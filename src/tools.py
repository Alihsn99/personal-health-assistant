"""Functions exposed to Gemini as tools (via automatic function calling).

Profile and daily logs live in Supabase (Postgres) so they persist and sync
across devices when this app is deployed publicly -- local file storage
doesn't survive a Streamlit Community Cloud restart. The research corpus
stays in local chromadb since it's static public PubMed data with no need
for live multi-device sync.
"""

import os
from datetime import date
from pathlib import Path

import chromadb
from supabase import Client, create_client

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"

_chroma_client = chromadb.PersistentClient(path=str(CORPUS_DIR / "chroma_db"))
_collection = _chroma_client.get_or_create_collection(name="health_research")

_supabase: Client | None = None


def _sb() -> Client:
    global _supabase
    if _supabase is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL/SUPABASE_KEY not set. Copy .env.example to .env and add them "
                "(free project at https://supabase.com)."
            )
        _supabase = create_client(url, key)
    return _supabase


def get_profile() -> dict:
    resp = _sb().table("profile").select("data").eq("id", 1).maybe_single().execute()
    profile = resp.data["data"] if resp and resp.data else {}
    dob = profile.get("date_of_birth")
    if dob:
        born = date.fromisoformat(dob)
        today = date.today()
        profile["age"] = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return profile


def update_profile(updates: dict) -> dict:
    """Shallow-merges `updates` into the stored profile and saves it."""
    profile = get_profile()
    profile.pop("age", None)  # computed on read, don't persist it
    for key, value in updates.items():
        if isinstance(profile.get(key), dict) and isinstance(value, dict):
            profile[key].update(value)
        else:
            profile[key] = value
    _sb().table("profile").upsert({"id": 1, "data": profile}).execute()
    return get_profile()


def get_log_for_date(entry_date: str) -> dict | None:
    """Gets the existing log row for a date, if one exists."""
    resp = _sb().table("logs").select("*").eq("entry_date", entry_date).execute()
    return resp.data[0] if resp.data else None


def log_entry(
    weight_kg: int | float | None = None,
    calories: int | float | None = None,
    protein_g: int | float | None = None,
    fat_g: int | float | None = None,
    carbs_g: int | float | None = None,
    workout: str = "",
    notes: str = "",
    entry_date: str | None = None,
) -> dict:
    """Records a meal or activity for the day. When the user describes food,
    pass YOUR OWN estimate of that meal's calories/protein/fat/carbs based on
    what they said they ate -- don't ask them to calculate it, and mention in
    your reply that the numbers are estimates, not lab-measured values.

    IMPORTANT: pass only THIS meal's/activity's numbers, never a running
    total -- calories/protein/fat/carbs are automatically added to whatever
    is already logged for the day, so logging breakfast then separately
    logging lunch correctly accumulates both. Do not attempt to add up the
    day's total yourself; call get_log_for_date to see the current running
    total if you need it. weight_kg overwrites (you only weigh in once
    meaningfully per day); workout/notes append as separate entries rather
    than overwriting, so multiple activities/meals in a day all stay visible."""
    entry_date = entry_date or date.today().isoformat()
    existing = get_log_for_date(entry_date)
    row = existing or {"entry_date": entry_date}
    row_id = row.pop("id", None)
    row.pop("created_at", None)

    if weight_kg is not None:
        row["weight_kg"] = weight_kg

    for key, value in {"calories": calories, "protein_g": protein_g, "fat_g": fat_g, "carbs_g": carbs_g}.items():
        if value is not None:
            row[key] = (row.get(key) or 0) + value

    for key, value in {"workout": workout, "notes": notes}.items():
        if value:
            row[key] = f"{row[key]}; {value}" if row.get(key) else value

    if row_id:
        _sb().table("logs").update(row).eq("id", row_id).execute()
    else:
        _sb().table("logs").insert(row).execute()
    return row


def get_recent_logs(n: int = 14) -> list[dict]:
    """Gets the user's most recent daily log entries, oldest first."""
    resp = _sb().table("logs").select("*").order("entry_date", desc=True).limit(n).execute()
    rows = resp.data or []
    rows.reverse()
    return rows


def search_research(query: str, n_results: int = 5) -> list[dict]:
    """Semantic search over the curated PubMed abstract/full-text corpus."""
    if _collection.count() == 0:
        return []
    results = _collection.query(query_texts=[query], n_results=min(n_results, _collection.count()))
    hits = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        hits.append(
            {
                "title": meta.get("title"),
                "year": meta.get("year"),
                "journal": meta.get("journal"),
                "url": meta.get("url"),
                "excerpt": doc[:600],
            }
        )
    return hits
