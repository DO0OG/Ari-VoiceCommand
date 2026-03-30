import { createAdminClient, getOrCreateDeveloper } from "../_shared.ts";

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const siteUrl = Deno.env.get("SITE_URL") ?? "http://localhost:3000";

  if (!code) {
    return Response.redirect(`${siteUrl}/dashboard?error=missing_code`, 302);
  }

  const supabase = createAdminClient();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session?.user) {
    return Response.redirect(`${siteUrl}/dashboard?error=auth_failed`, 302);
  }

  await getOrCreateDeveloper(supabase, data.session.user);

  const headers = new Headers({ Location: `${siteUrl}/dashboard` });
  headers.append(
    "Set-Cookie",
    `sb-access-token=${data.session.access_token}; Path=/; HttpOnly; Secure; SameSite=Lax`,
  );
  headers.append(
    "Set-Cookie",
    `sb-refresh-token=${data.session.refresh_token}; Path=/; HttpOnly; Secure; SameSite=Lax`,
  );
  return new Response(null, { status: 302, headers });
});
