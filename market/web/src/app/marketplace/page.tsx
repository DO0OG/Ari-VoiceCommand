import { Suspense } from "react";
import { fetchPlugins } from "@/lib/api";
import { PluginGrid } from "@/components/PluginGrid";
import { SearchBar } from "@/components/SearchBar";
import { Plugin } from "@/lib/types";

export default async function MarketplacePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const search = typeof params.search === "string" ? params.search : "";
  const sort = typeof params.sort === "string" ? params.sort : "created_at";
  let items: Plugin[] = [];
  try {
    const result = await fetchPlugins({ search, sort });
    items = result.items;
  } catch {
    // Edge Functions 미배포 또는 네트워크 오류 시 빈 목록으로 표시
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-12">
      <section className="rounded-[2rem] bg-white/50 p-8 shadow-card">
        <p className="text-sm uppercase tracking-[0.2em] text-ember">Ari Marketplace</p>
        <h1 className="mt-3 font-display text-5xl text-ink">검증된 Ari 플러그인을 한곳에서</h1>
        <p className="mt-4 max-w-2xl text-lg leading-8 text-ink/70">
          ClamAV, bandit, pylint, semgrep 기반 자동 심사를 통과한 플러그인만 노출합니다.
        </p>
      </section>
      <section className="mt-8">
        <Suspense>
          <SearchBar />
        </Suspense>
      </section>
      <section className="mt-8">
        <PluginGrid plugins={items} />
      </section>
    </main>
  );
}
