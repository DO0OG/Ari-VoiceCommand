import {
  corsOptions,
  createAdminClient,
  getOrCreateDeveloper,
  json,
  requireUser,
} from "../_shared.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return corsOptions();
  try {
    const supabase = createAdminClient();
    const user = await requireUser(supabase, req);
    const developer = await getOrCreateDeveloper(supabase, user);

    // DELETE: 반려/대기 플러그인 삭제
    if (req.method === "DELETE") {
      const { plugin_id } = await req.json();
      if (!plugin_id) return json({ error: "plugin_id required" }, 400);

      const { error } = await supabase
        .from("plugins")
        .delete()
        .eq("id", plugin_id)
        .eq("developer_id", developer.id);

      if (error) return json({ error: error.message }, 500);
      return json({ success: true });
    }

    // GET: 내 플러그인 목록
    const { data, error } = await supabase
      .from("plugins")
      .select("*")
      .eq("developer_id", developer.id)
      .order("created_at", { ascending: false });

    if (error) return json({ error: error.message }, 500);
    return json({ items: data ?? [] });
  } catch (error) {
    if (error instanceof Response) return error;
    return json({ error: error instanceof Error ? error.message : "Unexpected error" }, 500);
  }
});
