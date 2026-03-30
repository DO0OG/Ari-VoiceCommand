"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plugin } from "@/lib/types";
import { signInWithGitHub, supabase } from "@/lib/supabase";
import { useAuth } from "@/components/AuthProvider";

const statusLabel: Record<string, string> = {
  pending: "검증 중",
  approved: "승인됨",
  rejected: "반려됨",
};

export default function DashboardPage() {
  const { session, loading } = useAuth();
  const [plugins, setPlugins] = useState<Plugin[]>([]);

  async function loadPlugins() {
    const { data } = await supabase.functions.invoke("my-plugins");
    setPlugins((data as { items: Plugin[] })?.items ?? []);
  }

  async function deletePlugin(pluginId: string) {
    await supabase.functions.invoke("my-plugins", {
      method: "DELETE",
      body: { plugin_id: pluginId },
    });
    await loadPlugins();
  }

  useEffect(() => {
    if (session) loadPlugins();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (loading) {
    return <main className="p-10">로딩 중...</main>;
  }

  if (!session) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <div className="rounded-[2rem] bg-white/80 p-8 text-center shadow-card">
          <h1 className="font-display text-4xl text-ink">개발자 대시보드</h1>
          <p className="mt-4 text-ink/65">GitHub 로그인 후 업로드 상태와 심사 결과를 확인할 수 있습니다.</p>
          <button
            type="button"
            onClick={() => signInWithGitHub()}
            className="mt-6 rounded-full bg-ink px-5 py-3 text-white"
          >
            GitHub로 로그인
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl text-ink">내 플러그인</h1>
          <p className="mt-2 text-ink/60">{session.user.email}</p>
        </div>
        <Link href="/dashboard/upload" className="rounded-full bg-pine px-5 py-3 text-white">
          새 플러그인 업로드
        </Link>
      </div>

      <div className="mt-8 space-y-4">
        {plugins.map((plugin) => (
          <div key={plugin.id} className="rounded-3xl bg-white p-5 shadow-card">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-display text-2xl text-ink">{plugin.name}</p>
                <p className="text-sm text-ink/60">v{plugin.version}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-fog px-3 py-1 text-sm text-ink/70">
                  {statusLabel[plugin.status ?? "pending"]}
                </span>
                {(plugin.status === "rejected" || plugin.status === "pending") && (
                  <button
                    onClick={() => deletePlugin(plugin.id)}
                    className="rounded-full bg-red-100 px-3 py-1 text-sm text-red-600 hover:bg-red-200"
                  >
                    삭제
                  </button>
                )}
              </div>
            </div>
            {plugin.review_report?.summary ? (
              <p className="mt-3 text-sm text-ink/70">{plugin.review_report.summary}</p>
            ) : null}
          </div>
        ))}
      </div>
    </main>
  );
}
