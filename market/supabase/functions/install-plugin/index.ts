import { createAdminClient, json } from "../_shared.ts";

Deno.serve(async (req) => {
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
    .select("id, release_url, install_count")
    .eq("id", pluginId)
    .eq("status", "approved")
    .single();

  if (error || !plugin) {
    return json({ error: "Approved plugin not found" }, 404);
  }

  await supabase.from("installs").insert({ plugin_id: plugin.id });
  await supabase
    .from("plugins")
    .update({ install_count: Number(plugin.install_count ?? 0) + 1 })
    .eq("id", plugin.id);

  return json({ release_url: plugin.release_url });
});
