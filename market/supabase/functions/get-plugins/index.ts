import { createAdminClient, json, sanitizeSort } from "../_shared.ts";

Deno.serve(async (req) => {
  const supabase = createAdminClient();
  const url = new URL(req.url);
  const search = (url.searchParams.get("search") ?? "").trim();
  const sort = sanitizeSort(url.searchParams.get("sort") ?? "created_at");
  const page = Math.max(1, Number.parseInt(url.searchParams.get("page") ?? "1", 10));
  const limit = Math.min(50, Math.max(1, Number.parseInt(url.searchParams.get("limit") ?? "20", 10)));

  let query = supabase
    .from("plugins")
    .select("id, name, version, description, commands, permissions, install_count, created_at, developers(github_login)")
    .eq("status", "approved")
    .order(sort, { ascending: sort === "name" })
    .range((page - 1) * limit, page * limit - 1);

  if (search) {
    query = query.or(`name.ilike.%${search}%,description.ilike.%${search}%`);
  }

  const { data, error } = await query;
  if (error) {
    return json({ error: error.message }, 500);
  }
  return json({ items: data ?? [], page, limit });
});
