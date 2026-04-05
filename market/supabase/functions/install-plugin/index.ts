import { corsOptions, createAdminClient, json } from "../_shared.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return corsOptions();
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  const supabase = createAdminClient();
  const { plugin_id: pluginId } = await req.json();
  if (!pluginId) {
    return json({ error: "plugin_id is required" }, 400);
  }

  const { data: plugin, error } = await supabase
    .from("plugins")
    .select("id, name, entry, release_url, sha256, install_count")
    .eq("id", pluginId)
    .eq("status", "approved")
    .single();

  if (error || !plugin) {
    return json({ error: "Approved plugin not found" }, 404);
  }

  const { error: installError } = await supabase.rpc("record_plugin_install", {
    target_plugin_id: plugin.id,
  });
  if (installError) {
    return json({ error: installError.message }, 500);
  }

  return json({
    release_url: plugin.release_url,
    name: plugin.name,
    entry: plugin.entry,
    sha256: plugin.sha256,
  });
});
