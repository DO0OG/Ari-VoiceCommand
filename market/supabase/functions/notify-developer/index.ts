import { Resend } from "https://esm.sh/resend";
import { createAdminClient, json } from "../_shared.ts";

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  const { plugin_id: pluginId, status, report } = await req.json();
  if (!pluginId || !status) {
    return json({ error: "plugin_id and status are required" }, 400);
  }

  const supabase = createAdminClient();
  const { data: plugin, error } = await supabase
    .from("plugins")
    .select("name, version, developers(email, github_login)")
    .eq("id", pluginId)
    .single();

  if (error || !plugin) {
    return json({ error: "Plugin not found" }, 404);
  }
  if (!plugin.developers?.email) {
    return json({ sent: false, reason: "missing_email" });
  }

  const resend = new Resend(Deno.env.get("RESEND_API_KEY") ?? "");
  const stageReport = Object.entries(report?.stages ?? {})
    .map(([stage, value]) => {
      const typed = value as { passed?: boolean; detail?: unknown };
      return `${typed.passed ? "✅" : "❌"} ${stage}\n${
        typed.passed ? "통과" : JSON.stringify(typed.detail, null, 2)
      }`;
    })
    .join("\n\n");

  await resend.emails.send({
    ["from"]: `${"Ari Marketplace"} <${"noreply@your-domain.com"}>`,
    to: plugin.developers.email,
    subject: `[Ari Marketplace] ${plugin.name} ${status === "approved" ? "승인" : "반려"}`,
    text:
      `${plugin.developers.github_login}님의 플러그인 "${plugin.name} v${plugin.version}" 심사가 완료되었습니다.\n\n` +
      stageReport,
  });

  return json({ sent: true });
});
