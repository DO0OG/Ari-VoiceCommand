import { createClient, type SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2";

export const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type, apikey, x-client-info",
};

export const corsOptions = () =>
  new Response(null, { status: 204, headers: CORS_HEADERS });

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...CORS_HEADERS,
    },
  });

export function createAdminClient(): SupabaseClient {
  return createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  );
}

// 유저 JWT를 명시적으로 getUser(token)으로 검증
export async function requireUser(_adminClient: SupabaseClient, req: Request) {
  const authHeader = req.headers.get("Authorization") ?? "";
  if (!authHeader.startsWith("Bearer ")) {
    throw new Response(JSON.stringify({ error: "Missing authorization header" }), { status: 401 });
  }

  const token = authHeader.slice(7);
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_ANON_KEY") ?? "",
  );

  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) {
    throw new Response(JSON.stringify({ error: error?.message ?? "Unauthorized" }), { status: 401 });
  }

  return data.user;
}

export async function getOrCreateDeveloper(supabase: SupabaseClient, user: {
  id: string;
  email?: string | null;
  user_metadata?: Record<string, unknown>;
}) {
  const githubId = String(user.user_metadata?.provider_id ?? user.user_metadata?.sub ?? user.id);
  const githubLogin = String(
    user.user_metadata?.user_name ??
      user.user_metadata?.preferred_username ??
      user.user_metadata?.name ??
      "unknown",
  );

  const { data, error } = await supabase
    .from("developers")
    .upsert(
      {
        github_id: githubId,
        github_login: githubLogin,
        email: user.email ?? null,
      },
      { onConflict: "github_id" },
    )
    .select("*")
    .single();

  if (error || !data) {
    throw new Response(JSON.stringify({ error: "Developer upsert failed" }), { status: 500 });
  }
  return data;
}

export function sanitizeSort(sort: string) {
  const allowed = new Set(["created_at", "install_count", "name"]);
  return allowed.has(sort) ? sort : "created_at";
}
