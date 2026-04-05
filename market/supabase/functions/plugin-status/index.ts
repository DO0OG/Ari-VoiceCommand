import {
  corsOptions,
  createAdminClient,
  json,
  requireUser,
} from "../_shared.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return corsOptions();
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  try {
    const supabase = createAdminClient();
    const user = await requireUser(supabase, req);
    const { plugin_id: pluginId } = await req.json();
    const githubId = String(user.user_metadata?.provider_id ?? user.user_metadata?.sub ?? user.id);

    if (!pluginId) {
      return json({ error: "plugin_id is required" }, 400);
    }

    const { data: developer, error: developerError } = await supabase
      .from("developers")
      .select("id")
      .eq("github_id", githubId)
      .maybeSingle();
    if (developerError) {
      return json({ error: developerError.message }, 500);
    }
    if (!developer) {
      return json({ error: "Developer not found" }, 404);
    }

    const { data, error } = await supabase
      .from("plugins")
      .select("id, status, review_report, reviewed_at")
      .eq("id", pluginId)
      .eq("developer_id", developer.id)
      .maybeSingle();

    if (error) {
      return json({ error: error.message }, 500);
    }
    if (!data) {
      return json({ error: "Plugin not found" }, 404);
    }

    return json({ item: data });
  } catch (error) {
    if (error instanceof Response) return error;
    return json({ error: error instanceof Error ? error.message : "Unexpected error" }, 500);
  }
});
