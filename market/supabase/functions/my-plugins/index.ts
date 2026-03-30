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

    const { data, error } = await supabase
      .from("plugins")
      .select("*")
      .eq("developer_id", developer.id)
      .order("created_at", { ascending: false });

    if (error) {
      return json({ error: error.message }, 500);
    }
    return json({ items: data ?? [] });
  } catch (error) {
    if (error instanceof Response) {
      return error;
    }
    return json({ error: error instanceof Error ? error.message : "Unexpected error" }, 500);
  }
});
