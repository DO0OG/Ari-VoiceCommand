create extension if not exists pgcrypto;

create table if not exists public.developers (
  id uuid primary key default gen_random_uuid(),
  github_id text unique not null,
  github_login text not null,
  email text,
  created_at timestamptz not null default now()
);

create table if not exists public.plugins (
  id uuid primary key default gen_random_uuid(),
  developer_id uuid not null references public.developers(id) on delete cascade,
  name text not null,
  version text not null,
  api_version text not null default '1.0',
  description text,
  commands text[] not null default '{}',
  permissions text[] not null default '{}',
  entry text not null default 'main.py',
  zip_url text,
  release_url text,
  sha256 text,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  review_report jsonb not null default '{}'::jsonb,
  install_count integer not null default 0,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (developer_id, name, version)
);

create table if not exists public.installs (
  id uuid primary key default gen_random_uuid(),
  plugin_id uuid not null references public.plugins(id) on delete cascade,
  installed_at timestamptz not null default now()
);

alter table public.developers enable row level security;
alter table public.plugins enable row level security;
alter table public.installs enable row level security;

drop policy if exists "developers_self_select" on public.developers;
create policy "developers_self_select" on public.developers
  for select
  to authenticated
  using (github_id = auth.uid()::text);

drop policy if exists "developers_self_upsert" on public.developers;
create policy "developers_self_upsert" on public.developers
  for all
  to authenticated
  using (github_id = auth.uid()::text)
  with check (github_id = auth.uid()::text);

drop policy if exists "public_read_approved" on public.plugins;
create policy "public_read_approved" on public.plugins
  for select
  using (status = 'approved');

drop policy if exists "developers_read_own_plugins" on public.plugins;
create policy "developers_read_own_plugins" on public.plugins
  for select
  to authenticated
  using (
    developer_id in (
      select id
      from public.developers
      where github_id = auth.uid()::text
    )
  );

drop policy if exists "developers_write_own_plugins" on public.plugins;
create policy "developers_write_own_plugins" on public.plugins
  for all
  to authenticated
  using (
    developer_id in (
      select id
      from public.developers
      where github_id = auth.uid()::text
    )
  )
  with check (
    developer_id in (
      select id
      from public.developers
      where github_id = auth.uid()::text
    )
  );

drop policy if exists "public_insert_installs" on public.installs;
create policy "public_insert_installs" on public.installs
  for insert
  with check (true);

drop policy if exists "developers_read_own_installs" on public.installs;
create policy "developers_read_own_installs" on public.installs
  for select
  to authenticated
  using (
    plugin_id in (
      select p.id
      from public.plugins p
      join public.developers d on d.id = p.developer_id
      where d.github_id = auth.uid()::text
    )
  );

create index if not exists idx_plugins_status_created_at on public.plugins(status, created_at desc);
create index if not exists idx_plugins_status_install_count on public.plugins(status, install_count desc);
