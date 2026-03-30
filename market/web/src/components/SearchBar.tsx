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
    return () => { window.clearTimeout(handle); };
  }, [router, search, sort, searchParams]);

  return (
    <div className="glass grid gap-2 rounded-2xl p-2 md:grid-cols-[1fr_160px]">
      <input
        value={search}
        onChange={(e) => { setSearch(e.target.value); }}
        placeholder="플러그인 이름 또는 설명 검색"
        className="rounded-xl bg-transparent px-4 py-2.5 text-sm text-bright placeholder:text-muted outline-none"
      />
      <select
        value={sort}
        onChange={(e) => { setSort(e.target.value); }}
        className="rounded-xl bg-white/[0.06] px-3 py-2.5 text-sm text-subtle outline-none"
      >
        <option value="created_at">최신순</option>
        <option value="install_count">인기순</option>
        <option value="name">이름순</option>
      </select>
    </div>
  );
}
