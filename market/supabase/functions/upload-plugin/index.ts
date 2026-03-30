import * as zip from "https://deno.land/x/zipjs/index.js";
import {
  corsOptions,
  createAdminClient,
  getOrCreateDeveloper,
  json,
  requireUser,
} from "../_shared.ts";

const REQUIRED_FIELDS = ["name", "version", "api_version", "description", "entry"] as const;
const SUPPORTED_API_VERSIONS = new Set(["1.0"]);

type PluginMeta = {
  name: string;
  version: string;
  api_version: string;
  description: string;
  entry: string;
  commands?: string[];
  permissions?: string[];
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return corsOptions();
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  try {
    const supabase = createAdminClient();
    const user = await requireUser(supabase, req);
    const developer = await getOrCreateDeveloper(supabase, user);

    const formData = await req.formData();
    const file = formData.get("plugin");
    if (!(file instanceof File)) {
      return json({ error: "plugin file is required" }, 400);
    }
    if (!file.name.toLowerCase().endsWith(".zip")) {
      return json({ error: "plugin must be a zip file" }, 400);
    }

    const meta = await extractPluginJson(file);
    const validationError = validateMeta(meta);
    if (validationError) {
      return json({ error: validationError }, 400);
    }

    const filePath = `${user.id}/${meta.name}-${meta.version}.zip`;
    const uploadRes = await supabase.storage.from("plugin-uploads").upload(
      filePath,
      await file.arrayBuffer(),
      {
        contentType: "application/zip",
        upsert: true,
      },
    );
    if (uploadRes.error) {
      return json({ error: uploadRes.error.message }, 500);
    }

    const { data: plugin, error } = await supabase
      .from("plugins")
      .upsert(
        {
          developer_id: developer.id,
          name: meta.name,
          version: meta.version,
          api_version: meta.api_version,
          description: meta.description,
          commands: meta.commands ?? [],
          permissions: meta.permissions ?? [],
          entry: meta.entry,
          zip_url: uploadRes.data.path,
          status: "pending",
          review_report: {},
          reviewed_at: null,
        },
        { onConflict: "developer_id,name,version" },
      )
      .select("*")
      .single();

    if (error || !plugin) {
      return json({ error: error?.message ?? "plugin insert failed" }, 500);
    }

    await triggerValidation(plugin.id, user.id);
    return json({ plugin_id: plugin.id, status: plugin.status });
  } catch (error) {
    if (error instanceof Response) {
      return error;
    }
    return json({ error: error instanceof Error ? error.message : "Unexpected error" }, 500);
  }
});

async function extractPluginJson(file: File): Promise<PluginMeta> {
  const reader = new zip.ZipReader(new zip.BlobReader(file));
  const entries = await reader.getEntries();
  const metaEntry = entries.find((entry: { filename: string }) => entry.filename === "plugin.json");
  if (!metaEntry || !metaEntry.getData) {
    await reader.close();
    throw new Error("plugin.json not found in zip root");
  }
  const text = await metaEntry.getData(new zip.TextWriter());
  await reader.close();
  return JSON.parse(text);
}

function validateMeta(meta: PluginMeta): string | null {
  const requiredValues: Array<[typeof REQUIRED_FIELDS[number], string]> = [
    ["name", meta.name],
    ["version", meta.version],
    ["api_version", meta.api_version],
    ["description", meta.description],
    ["entry", meta.entry],
  ];
  for (const [field, value] of requiredValues) {
    if (String(value ?? "").trim() === "") {
      return `Missing required field: ${field}`;
    }
  }
  if (!SUPPORTED_API_VERSIONS.has(meta.api_version)) {
    return `Unsupported api_version: ${meta.api_version}`;
  }
  if (meta.entry.includes("/") || meta.entry.includes("\\")) {
    return "entry must be a root-level file";
  }
  if (!/^[A-Za-z0-9_.-]+$/.test(meta.name)) {
    return "name contains invalid characters";
  }
  return null;
}

async function triggerValidation(pluginId: string, developerId: string) {
  const repo = Deno.env.get("GH_REPO");
  const pat = Deno.env.get("GH_PAT");
  if (!repo || !pat) {
    return;
  }

  const response = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/validate-plugin.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${pat}`,
        "Content-Type": "application/json",
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: { plugin_id: pluginId, developer_id: developerId },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Failed to trigger validation: ${response.status} ${body}`);
  }
}
