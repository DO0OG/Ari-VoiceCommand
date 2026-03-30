import { Plugin } from "@/lib/types";

const FUNCTIONS_URL = process.env.NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL!;

export async function fetchPlugins(params?: { search?: string; sort?: string; page?: number }): Promise<{ items: Plugin[] }> {
  try {
    if (!FUNCTIONS_URL) return { items: [] };
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.sort) qs.set("sort", params.sort);
    if (params?.page) qs.set("page", String(params.page));
    const url = `${FUNCTIONS_URL}/get-plugins${qs.size ? `?${qs}` : ""}`;
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) return { items: [] };
    return (await response.json()) as { items: Plugin[] };
  } catch {
    return { items: [] };
  }
}

export async function fetchPlugin(pluginId: string) {
  const url = new URL(`${FUNCTIONS_URL}/get-plugin`);
  url.searchParams.set("plugin_id", pluginId);
  const response = await fetch(url.toString(), { cache: "no-store" });
  if (!response.ok) {
    throw new Error("플러그인 상세 정보를 불러오지 못했습니다.");
  }
  return (await response.json()) as Plugin;
}
