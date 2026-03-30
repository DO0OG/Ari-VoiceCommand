import { createAdminClient, json } from "../_shared.ts";

Deno.serve(async (req) => {
  const supabase = createAdminClient();
  const url = new URL(req.url);
  const pluginId = url.searchParams.get("plugin_id");

  if (!pluginId) {
    return json({ error: "plugin_id is required" }, 400);
  }

  const { data, error } = await supabase
    .from("plugins")
    .select(`
      id,
      name,
      version,
      api_version,
      description,
      commands,
      permissions,
      entry,
      status,
      install_count,
      created_at,
      reviewed_at,
      release_url,
      review_report,
      developers(github_login)
    `)
    .eq("id", pluginId)
    .eq("status", "approved")
    .maybeSingle();

  if (error) {
    return json({ error: error.message }, 500);
  }
  if (!data) {
    return json({ error: "Plugin not found" }, 404);
  }
  return json(data);
});
