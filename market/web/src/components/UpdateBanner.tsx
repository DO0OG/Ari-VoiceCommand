"use client";

import { useSearchParams } from "next/navigation";

export function UpdateBanner() {
  const name = useSearchParams().get("update");
  if (!name) return null;
  return (
    <div className="mb-6 rounded-xl border border-[rgba(167,139,250,0.3)] bg-[rgba(167,139,250,0.08)] px-4 py-3 text-sm text-[#a78bfa]">
      <strong>{name}</strong> 업데이트 — 새 버전 번호가 포함된 ZIP 파일을 업로드하세요.
      <span className="ml-2 text-xs text-muted">(같은 버전 재업로드 시 덮어씀)</span>
    </div>
  );
}
