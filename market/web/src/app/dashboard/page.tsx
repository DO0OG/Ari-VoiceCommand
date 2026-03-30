"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plugin } from "@/lib/types";
import { signInWithGitHub, supabase } from "@/lib/supabase";
import { useAuth } from "@/components/AuthProvider";

const statusMeta: Record<string, { label: string; color: string; dot: string }> = {
  pending:  { label: "검증 중",  color: "text-[#60a5fa] bg-[rgba(96,165,250,0.1)]",  dot: "bg-[#60a5fa] animate-pulse" },
  approved: { label: "승인됨",   color: "text-[#4ade80] bg-[rgba(74,222,128,0.1)]",  dot: "bg-[#4ade80]" },
  rejected: { label: "반려됨",   color: "text-red-400   bg-[rgba(248,113,113,0.1)]", dot: "bg-red-400" },
};

function ReviewReport({ report }: { report: Plugin["review_report"] }) {
  if (!report?.stages && !report?.summary) return null;
  const stages = report.stages ?? {};
  const stageLabels: Record<string, string> = {
    clamav: "바이러스 스캔",
    bandit: "Bandit 보안",
    pylint: "Pylint 품질",
    semgrep: "Semgrep 스캔",
  };
  return (
    <div className="mt-4 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
      {report.summary && (
        <p className="mb-3 text-sm text-subtle">{report.summary}</p>
      )}
      {Object.keys(stages).length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Object.entries(stages).map(([key, val]) => (
            <div key={key} className="rounded-lg bg-white/[0.03] px-3 py-2 text-center">
              <p className="text-xs text-muted">{stageLabels[key] ?? key}</p>
              <p className={`mt-1 text-sm font-semibold ${val.passed ? "text-[#4ade80]" : "text-red-400"}`}>
                {val.passed ? "통과" : "실패"}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { session, loading } = useAuth();
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function loadPlugins() {
    const { data } = await supabase.functions.invoke("my-plugins");
    setPlugins((data as { items: Plugin[] })?.items ?? []);
  }

  async function handleDelete(pluginId: string) {
    if (!confirm("이 플러그인을 삭제하시겠습니까?")) return;
    setDeleting(pluginId);
    await supabase.functions.invoke("my-plugins", {
      method: "DELETE",
      body: { plugin_id: pluginId },
    });
    setDeleting(null);
    await loadPlugins();
  }

  useEffect(() => {
    if (session) loadPlugins();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-subtle">로딩 중...</p>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-20 text-center">
        <h1 className="text-4xl font-bold text-bright">개발자 대시보드</h1>
        <p className="mt-4 text-subtle">GitHub 로그인 후 업로드 상태와 심사 결과를 확인할 수 있습니다.</p>
        <button
          type="button"
          onClick={() => signInWithGitHub()}
          className="mt-8 rounded-full bg-accent px-6 py-3 text-sm font-semibold text-white hover:opacity-90"
        >
          GitHub로 로그인
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      {/* 헤더 */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-bright">내 플러그인</h1>
          <p className="mt-1 text-sm text-muted">{session.user.email}</p>
        </div>
        <Link
          href="/dashboard/upload"
          className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90"
        >
          + 새 플러그인 업로드
        </Link>
      </div>

      {/* 통계 */}
      {plugins.length > 0 && (
        <div className="mt-6 grid grid-cols-3 gap-3">
          {(["approved", "pending", "rejected"] as const).map((s) => (
            <div key={s} className="glass rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-bright">{plugins.filter((p) => p.status === s).length}</p>
              <p className="mt-1 text-xs text-muted">{statusMeta[s].label}</p>
            </div>
          ))}
        </div>
      )}

      {/* 플러그인 목록 */}
      <div className="mt-6 space-y-3">
        {plugins.length === 0 ? (
          <div className="rounded-2xl border border-white/[0.06] p-12 text-center text-muted">
            <p className="text-4xl">📦</p>
            <p className="mt-3 text-sm">업로드한 플러그인이 없습니다.</p>
            <Link href="/dashboard/upload" className="mt-4 inline-block text-sm text-[#a78bfa] hover:underline">
              첫 플러그인 업로드하기 →
            </Link>
          </div>
        ) : (
          plugins.map((plugin) => {
            const sm = statusMeta[plugin.status ?? "pending"];
            const isExpanded = expanded === plugin.id;

            return (
              <div key={plugin.id} className="glass rounded-2xl p-5">
                {/* 메인 행 */}
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-lg font-semibold text-bright">{plugin.name}</span>
                      <span className="text-xs text-muted">v{plugin.version}</span>
                      <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${sm.color}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${sm.dot}`} />
                        {sm.label}
                      </span>
                    </div>
                    {plugin.description && (
                      <p className="mt-1 truncate text-sm text-subtle">{plugin.description}</p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted">
                      <span>API {plugin.api_version ?? "1.0"}</span>
                      <span>·</span>
                      <span>설치 {plugin.install_count ?? 0}회</span>
                      <span>·</span>
                      <span>{new Date(plugin.created_at).toLocaleDateString("ko-KR")}</span>
                      {plugin.reviewed_at && (
                        <>
                          <span>·</span>
                          <span>심사 {new Date(plugin.reviewed_at).toLocaleDateString("ko-KR")}</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* 액션 버튼 */}
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {plugin.review_report && (
                      <button
                        onClick={() => setExpanded(isExpanded ? null : plugin.id)}
                        className="rounded-lg border border-white/[0.08] px-3 py-1.5 text-xs text-subtle hover:border-white/20 hover:text-bright"
                      >
                        {isExpanded ? "접기" : "심사 결과"}
                      </button>
                    )}
                    {plugin.status === "approved" && plugin.release_url && (
                      <button
                        onClick={async () => {
                          await supabase.functions.invoke("install-plugin", {
                            body: { plugin_id: plugin.id },
                          });
                          window.open(plugin.release_url!, "_blank");
                          await loadPlugins();
                        }}
                        className="rounded-lg border border-[rgba(74,222,128,0.3)] px-3 py-1.5 text-xs text-[#4ade80] hover:bg-[rgba(74,222,128,0.1)]"
                      >
                        다운로드
                      </button>
                    )}
                    <Link
                      href={`/dashboard/upload?update=${encodeURIComponent(plugin.name)}`}
                      className="rounded-lg border border-[rgba(167,139,250,0.3)] px-3 py-1.5 text-xs text-[#a78bfa] hover:bg-[rgba(167,139,250,0.1)]"
                    >
                      업데이트
                    </Link>
                    <button
                      onClick={() => handleDelete(plugin.id)}
                      disabled={deleting === plugin.id}
                      className="rounded-lg border border-red-500/30 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-40"
                    >
                      {deleting === plugin.id ? "삭제 중..." : "삭제"}
                    </button>
                  </div>
                </div>

                {/* 명령어 태그 */}
                {(plugin.commands?.length ?? 0) > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {plugin.commands!.map((cmd) => (
                      <span key={cmd} className="rounded-full bg-[rgba(124,58,237,0.15)] px-2 py-0.5 text-[11px] text-[#a78bfa]">
                        {cmd}
                      </span>
                    ))}
                  </div>
                )}

                {/* 심사 결과 상세 */}
                {isExpanded && <ReviewReport report={plugin.review_report} />}
              </div>
            );
          })
        )}
      </div>
    </main>
  );
}
