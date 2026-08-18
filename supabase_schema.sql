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
