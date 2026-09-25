-- Run this once in Supabase: Project -> SQL Editor -> New query -> paste -> Run.

create table if not exists profile (
  id int primary key default 1,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists logs (
  id bigserial primary key,
  entry_date date not null default current_date,
  weight_kg numeric,
  calories numeric,
  protein_g numeric,
  workout text,
  notes text,
  created_at timestamptz not null default now()
);

-- Supabase enables RLS by default on new projects, which blocks all access
-- until a policy exists. This app has no per-user auth -- the whole thing is
-- gated by the Streamlit APP_PASSWORD instead -- so disable RLS here rather
-- than writing policies for a single-user app.
alter table profile disable row level security;
alter table logs disable row level security;
