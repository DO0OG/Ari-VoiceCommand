insert into storage.buckets (id, name, public, file_size_limit)
values ('plugin-uploads', 'plugin-uploads', false, 5242880)
on conflict (id) do nothing;

insert into storage.buckets (id, name, public)
values ('plugin-releases', 'plugin-releases', true)
on conflict (id) do nothing;

drop policy if exists "auth_upload_only" on storage.objects;
create policy "auth_upload_only" on storage.objects
  for insert
  to authenticated
  with check (bucket_id = 'plugin-uploads');

drop policy if exists "auth_read_own_uploads" on storage.objects;
create policy "auth_read_own_uploads" on storage.objects
  for select
  to authenticated
  using (bucket_id = 'plugin-uploads');

drop policy if exists "service_manage_uploads" on storage.objects;
create policy "service_manage_uploads" on storage.objects
  for all
  to service_role
  using (bucket_id in ('plugin-uploads', 'plugin-releases'))
  with check (bucket_id in ('plugin-uploads', 'plugin-releases'));

drop policy if exists "public_download_releases" on storage.objects;
create policy "public_download_releases" on storage.objects
  for select
  using (bucket_id = 'plugin-releases');
