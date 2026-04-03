alter table if exists public.plugins
  add column if not exists sha256 text;
