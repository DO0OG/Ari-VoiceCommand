create or replace function public.record_plugin_install(target_plugin_id uuid)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  synced_count integer;
begin
  insert into public.installs (plugin_id)
  values (target_plugin_id);

  select count(*)
  into synced_count
  from public.installs
  where plugin_id = target_plugin_id;

  update public.plugins
  set install_count = synced_count
  where id = target_plugin_id;

  return synced_count;
end;
$$;

grant execute on function public.record_plugin_install(uuid) to anon, authenticated, service_role;
