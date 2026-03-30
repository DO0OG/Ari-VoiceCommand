"use client";

import { useState, useRef, useCallback } from "react";
import JSZip from "jszip";
import { supabase } from "@/lib/supabase";

type PluginMeta = {
  name: string;
  version: string;
  api_version: string;
  description: string;
  entry: string;
  commands?: string[];
  permissions?: string[];
};

type UploadState = "idle" | "uploading" | "pending" | "done" | "error";

async function extractPluginJson(file: File): Promise<PluginMeta> {
  const zip = await JSZip.loadAsync(file);
  const entry = zip.file("plugin.json");
  if (!entry) throw new Error("plugin.json 파일이 ZIP 루트에 없습니다.");
  return JSON.parse(await entry.async("text"));
}

export function UploadForm() {
  const [meta, setMeta] = useState<PluginMeta | null>(null);
  const [status, setStatus] = useState<UploadState>("idle");
  const [message, setMessage] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setStatus("idle");
    setMessage("");
    setMeta(null);
    try {
      const parsed = await extractPluginJson(file);
      if (parsed.api_version !== "1.0") {
        throw new Error(`api_version "${parsed.api_version}"은 지원되지 않습니다.`);
      }
      setMeta(parsed);
      await upload(file);
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "업로드 실패");
    }
  }

  async function upload(file: File) {
    setStatus("uploading");
    // getUser()를 먼저 호출해 만료된 토큰을 자동 갱신시킴
    await supabase.auth.getUser();
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) throw new Error("로그인이 필요합니다.");

    const body = new FormData();
    body.append("plugin", file);

    const response = await fetch(
      `${process.env.NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL}/upload-plugin`,
      { method: "POST", headers: { Authorization: `Bearer ${token}` }, body },
    );
    const rawText = await response.text();
    let payload: Record<string, string> = {};
    try { payload = JSON.parse(rawText); } catch { /* non-JSON */ }
    if (!response.ok) {
      throw new Error(payload.error ?? payload.message ?? `HTTP ${response.status}: ${rawText.slice(0, 200)}`);
    }

    setStatus("pending");
    setMessage(`검증이 시작되었습니다. plugin_id: ${payload.plugin_id}`);
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }, []);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const onDragLeave = useCallback(() => setDragging(false), []);

  const statusConfig = {
    idle:      { color: "", text: "" },
    uploading: { color: "text-[#a78bfa]", text: "⏫ 업로드 중..." },
    pending:   { color: "text-[#60a5fa]", text: "🔍 검증 중..." },
    done:      { color: "text-[#4ade80]", text: "✅ 완료" },
    error:     { color: "text-red-400",   text: "❌ 오류" },
  };

  return (
    <div className="glass rounded-2xl p-6 shadow-card">
      <h2 className="text-xl font-semibold text-bright">플러그인 업로드</h2>
      <p className="mt-1 text-sm text-muted">ZIP 파일에 main.py와 plugin.json이 포함되어야 합니다.</p>

      {/* 드롭존 */}
      <div
        onClick={() => inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`mt-5 flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 text-center transition
          ${dragging
            ? "border-accent bg-[rgba(124,58,237,0.12)] text-[#a78bfa]"
            : "border-white/10 hover:border-white/20 hover:bg-white/[0.03] text-muted"
          }`}
      >
        <span className="text-3xl">{dragging ? "📂" : "📦"}</span>
        <div>
          <p className="text-sm font-medium text-subtle">
            {dragging ? "여기에 놓으세요" : "클릭하거나 ZIP 파일을 드래그하세요"}
          </p>
          <p className="mt-1 text-xs text-muted">최대 5MB · .zip 형식</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
      </div>

      {/* 미리보기 */}
      {meta && (
        <div className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 text-sm">
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">plugin.json</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-subtle">
            <span className="text-muted">이름</span><span className="text-bright">{meta.name}</span>
            <span className="text-muted">버전</span><span>{meta.version}</span>
            <span className="text-muted">API</span>
            <span className={meta.api_version === "1.0" ? "text-[#4ade80]" : "text-red-400"}>
              {meta.api_version}
            </span>
            <span className="text-muted">진입점</span><span>{meta.entry}</span>
            {(meta.commands?.length ?? 0) > 0 && (
              <>
                <span className="text-muted">명령어</span>
                <span className="flex flex-wrap gap-1">
                  {meta.commands!.map((c) => (
                    <span key={c} className="rounded-full bg-[rgba(124,58,237,0.15)] px-2 py-0.5 text-[11px] text-[#a78bfa]">
                      {c}
                    </span>
                  ))}
                </span>
              </>
            )}
          </div>
        </div>
      )}

      {/* 상태 */}
      {status !== "idle" && (
        <p className={`mt-4 text-sm ${statusConfig[status].color}`}>
          {statusConfig[status].text}
          {message && <span className="ml-1 text-muted text-xs">{message}</span>}
        </p>
      )}
    </div>
  );
}
