import { Plugin } from "@/lib/types";

const FUNCTIONS_URL = process.env.NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL!;

export async function fetchPlugins(params?: { search?: string; sort?: string; page?: number }) {
  const url = new URL(`${FUNCTIONS_URL}/get-plugins`);
  if (params?.search) {
    url.searchParams.set("search", params.search);
  }
  if (params?.sort) {
    url.searchParams.set("sort", params.sort);
  }
  if (params?.page) {
    url.searchParams.set("page", String(params.page));
  }

  const response = await fetch(url.toString(), { cache: "no-store" });
  if (!response.ok) {
    throw new Error("플러그인 목록을 불러오지 못했습니다.");
  }
  return (await response.json()) as { items: Plugin[] };
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
