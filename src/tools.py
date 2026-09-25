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
    weight_kg: float | None = None,
    calories: float | None = None,
    protein_g: float | None = None,
    workout: str = "",
    notes: str = "",
    entry_date: str | None = None,
) -> dict:
    """Records or updates the day's log entry. Merges into any existing row for
    that date rather than inserting a new one, so a second log the same day
    (e.g. calories added in the evening after a morning weigh-in) updates the
    day's entry instead of creating a duplicate row that would double-count in
    trends or confuse 'what did I log today' questions."""
    entry_date = entry_date or date.today().isoformat()
    existing = get_log_for_date(entry_date)
    row = existing or {"entry_date": entry_date}
    row_id = row.pop("id", None)
    row.pop("created_at", None)

    for key, value in {
        "weight_kg": weight_kg,
        "calories": calories,
        "protein_g": protein_g,
        "workout": workout,
        "notes": notes,
    }.items():
        if value not in (None, ""):
            row[key] = value

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
