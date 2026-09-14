alter table public.plugins
  add column if not exists submission_id uuid;

update public.plugins
set submission_id = gen_random_uuid()
where submission_id is null;

alter table public.plugins
  alter column submission_id set default gen_random_uuid(),
  alter column submission_id set not null;

create unique index if not exists idx_plugins_submission_id
  on public.plugins(submission_id);

-- Existing rows keyed by provider metadata are intentionally left untouched.
-- Reassigning them requires an operator-confirmed mapping to auth.users.

drop policy if exists "developers_write_own_plugins" on public.plugins;

drop policy if exists "developers_insert_own_plugins" on public.plugins;
create policy "developers_insert_own_plugins" on public.plugins
  for insert
  to authenticated
  with check (
    developer_id in (
      select id
      from public.developers
      where github_id = auth.uid()::text
    )
  );

drop policy if exists "developers_update_own_plugins" on public.plugins;
create policy "developers_update_own_plugins" on public.plugins
  for update
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

drop policy if exists "developers_delete_own_plugins" on public.plugins;
create policy "developers_delete_own_plugins" on public.plugins
  for delete
  to authenticated
  using (
    developer_id in (
      select id
      from public.developers
      where github_id = auth.uid()::text
    )
  );

revoke insert, update on table public.plugins from public, anon, authenticated;

grant all on table public.plugins to service_role;

grant insert (
  developer_id,
  name,
  version,
  api_version,
  description,
  commands,
  permissions,
  entry,
  zip_url
) on table public.plugins to authenticated;

grant update (
  developer_id,
  name,
  version,
  api_version,
  description,
  commands,
  permissions,
  entry,
  zip_url
) on table public.plugins to authenticated;
