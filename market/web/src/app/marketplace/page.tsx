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
    <main className="mx-auto max-w-6xl px-6 pb-20">
      {/* 히어로 */}
      <section className="py-16 text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-[#a78bfa]">
          Ari Plugin Marketplace
        </p>
        <h1 className="mt-4 text-5xl font-bold leading-tight tracking-tight text-bright">
          검증된 플러그인을
          <br />
          <span className="gradient-text">한 곳에서</span>
        </h1>
        <p className="mx-auto mt-5 max-w-lg text-base leading-7 text-subtle">
          ClamAV · bandit · pylint · semgrep 4단계 자동 심사를 통과한 플러그인만 게시됩니다.
        </p>
      </section>

      {/* 검색 */}
      <section className="mb-8">
        <Suspense>
          <SearchBar />
        </Suspense>
      </section>

      {/* 그리드 */}
      <section>
        <PluginGrid plugins={items} />
      </section>
    </main>
  );
}
