"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export function SearchBar() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [sort, setSort] = useState(searchParams.get("sort") ?? "created_at");

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const params = new URLSearchParams(searchParams.toString());
      if (search) {
        params.set("search", search);
      } else {
        params.delete("search");
      }
      params.set("sort", sort);
      router.replace(`/marketplace?${params.toString()}`);
    }, 300);
    return () => window.clearTimeout(handle);
  }, [router, search, sort, searchParams]);

  return (
    <div className="grid gap-3 rounded-3xl bg-white/75 p-4 shadow-card md:grid-cols-[1fr_180px]">
      <input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="플러그인 이름 또는 설명 검색"
        className="rounded-2xl border border-ink/10 bg-fog px-4 py-3 outline-none"
      />
      <select
        value={sort}
        onChange={(event) => setSort(event.target.value)}
        className="rounded-2xl border border-ink/10 bg-fog px-4 py-3 outline-none"
      >
        <option value="created_at">최신순</option>
        <option value="install_count">인기순</option>
        <option value="name">이름순</option>
      </select>
    </div>
  );
}
