# Personal Health Assistant (prototype)

A single-user assistant that reasons about the muscle-building vs. longevity
tradeoff (protein/mTOR/IGF-1 signaling vs. caloric restriction/AMPK pathways),
grounded in a curated corpus of PubMed research and your own profile/logs.

Not medical advice — informational research synthesis only.

## Local setup

```
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with:
- `GEMINI_API_KEY` — free tier, no card required: https://aistudio.google.com/apikey
- `SUPABASE_URL` / `SUPABASE_KEY` — free project at https://supabase.com (see below)

### Supabase (profile + logs storage)

Local JSON/CSV files don't survive a Streamlit Community Cloud restart, so
profile and daily logs live in a small hosted Postgres database instead:

1. Create a free project at https://supabase.com (no card required).
2. In the SQL Editor, run `supabase_schema.sql` from this repo to create the tables.
3. In Project Settings -> API, copy the Project URL and the `anon` public key into `.env`.
4. If you have existing local data in `data/profile.json` / `data/log.csv`, migrate it once:
   ```
   python src/migrate_to_supabase.py
   ```

### Research corpus

Pulls ~150 papers from PubMed on protein intake, mTOR/IGF-1/growth hormone
signaling, caloric restriction, and longevity -- fetching free full text from
PMC where available, abstracts otherwise. Takes several minutes; only needs
to be run once (re-running is cheap and additive, skips papers already seen):

```
python src/ingest_research.py
```

## Run locally

```
streamlit run app.py
```

## Deploying publicly (Streamlit Community Cloud)

The corpus (`corpus/chroma_db/`) is committed to this repo so the deployed
app has it immediately, without re-running ingestion in the cloud.

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. Go to https://share.streamlit.io, sign in with GitHub, and deploy this repo (`app.py` as the entry point).
3. In the app's Settings -> Secrets, paste the contents of `.streamlit/secrets.toml.example`
   filled in with your real values, including an `APP_PASSWORD` -- the app has
   no login otherwise, and it holds real personal health data plus a live API key.

## How it works

- **Profile & logs (Supabase)**: your stats, goals, priority weighting, and daily entries.
- `corpus/chroma_db/` — local vector store of PubMed research (built by `ingest_research.py`), committed to the repo since it's static public data.
- `src/tools.py` — functions Gemini can call: read/update profile, log entries, search research.
- `src/agent.py` — builds the Gemini chat session (automatic function calling + system prompt).
- `app.py` — Streamlit chat UI, with a password gate for the public deployment.

## Extending the corpus

Edit the `TOPICS` list in `src/ingest_research.py` and re-run it — it skips
papers already in the store, so re-running is cheap and additive.
