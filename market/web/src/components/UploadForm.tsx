"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import JSZip from "jszip";
import { supabase } from "@/lib/supabase";
import {
  MAX_PLUGIN_SIZE_LABEL,
  validatePluginArchiveSize,
} from "@/lib/pluginUpload";

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

function getStatusConfig(status: UploadState): { color: string; text: string } {
  switch (status) {
    case "uploading":
      return { color: "text-[#a78bfa]", text: "⏫ 업로드 중..." };
    case "pending":
      return { color: "text-[#60a5fa]", text: "🔍 검증 중... (자동으로 결과가 표시됩니다)" };
    case "done":
      return { color: "text-[#4ade80]", text: "✅ 승인 완료" };
    case "error":
      return { color: "text-red-400", text: "❌ 오류" };
    case "idle":
    default:
      return { color: "", text: "" };
  }
}

async function extractPluginJson(file: File): Promise<PluginMeta> {
  const zip = await JSZip.loadAsync(file);
  const metaEntry = zip.file("plugin.json");
  if (!metaEntry) throw new Error("plugin.json 파일이 ZIP 루트에 없습니다.");
  const meta = JSON.parse(await metaEntry.async("text")) as PluginMeta;
  if (!meta.entry) {
    throw new Error('plugin.json에 "entry" 값이 필요합니다.');
  }
  if (!zip.file(meta.entry)) {
    throw new Error(`ZIP 루트에 entry 파일(${meta.entry})이 없습니다.`);
  }
  return meta;
}

export function UploadForm() {
  const [meta, setMeta] = useState<PluginMeta | null>(null);
  const [status, setStatus] = useState<UploadState>("idle");
  const [message, setMessage] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activePollPluginIdRef = useRef<string | null>(null);
  const pollAttemptsRef = useRef(0);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
      activePollPluginIdRef.current = null;
    };
  }, []);

  function clearPolling() {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
    activePollPluginIdRef.current = null;
    pollAttemptsRef.current = 0;
  }

  function startPolling(pluginId: string) {
    clearPolling();
    activePollPluginIdRef.current = pluginId;

    const pollOnce = () => {
      pollAttemptsRef.current += 1;
      void (async () => {
        try {
          const { data, error } = await supabase.functions.invoke("plugin-status", {
            body: { plugin_id: pluginId },
          });
          if (activePollPluginIdRef.current !== pluginId) return;
          if (error) {
            if (pollAttemptsRef.current >= 45) {
              clearPolling();
              setStatus("error");
              setMessage(error.message ?? "검증 상태를 확인하지 못했습니다.");
              return;
            }
          } else {
            const plugin = (
              data as { item?: { status: string; review_report?: { summary?: string } } }
            ).item;
            if (plugin && plugin.status !== "pending") {
              clearPolling();
              if (plugin.status === "approved") {
                setStatus("done");
                setMessage("플러그인이 승인되었습니다! 마켓플레이스에 게시됩니다.");
              } else {
                setStatus("error");
                setMessage(plugin.review_report?.summary ?? "검증에서 반려되었습니다.");
              }
              return;
            }
          }
        } catch {
          if (activePollPluginIdRef.current !== pluginId) return;
          if (pollAttemptsRef.current >= 45) {
            clearPolling();
            setStatus("error");
            setMessage("검증 상태를 확인하지 못했습니다.");
            return;
          }
        }
        if (activePollPluginIdRef.current === pluginId) {
          pollRef.current = setTimeout(pollOnce, 4000);
        }
      })();
    };

    pollOnce();
  }

  async function handleFile(file: File) {
    clearPolling();
    setStatus("idle");
    setMessage("");
    setMeta(null);
    try {
      const sizeError = validatePluginArchiveSize(file);
      if (sizeError) {
        throw new Error(sizeError);
      }
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

    const { data: { user } } = await supabase.auth.getUser();
    if (!user) throw new Error("로그인이 필요합니다.");

    const body = new FormData();
    body.append("plugin", file);

    const { data: payload, error } = await supabase.functions.invoke("upload-plugin", { body });
    if (error) {
      let msg = error.message ?? "업로드 실패";
      try {
        const ctx = (error as { context?: unknown }).context;
        if (ctx instanceof Response) {
          const j = await ctx.clone().json();
          msg = j.error ?? j.message ?? msg;
        }
      } catch { /* ignore */ }
      throw new Error(msg);
    }

    const pluginId = (payload as { plugin_id: string }).plugin_id;
    setStatus("pending");
    setMessage("GitHub Actions 검증 파이프라인이 실행 중입니다...");
    startPolling(pluginId);
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      void handleFile(file);
    }
  }, []);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const onDragLeave = useCallback(() => { setDragging(false); }, []);

  const statusView = getStatusConfig(status);

  return (
    <div className="glass rounded-2xl p-6 shadow-card">
      <h2 className="text-xl font-semibold text-bright">플러그인 업로드</h2>
      <p className="mt-1 text-sm text-muted">ZIP 루트에 plugin.json과 entry로 지정한 Python 파일이 포함되어야 합니다.</p>

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
          <p className="mt-1 text-xs text-muted">최대 {MAX_PLUGIN_SIZE_LABEL} · .zip 형식</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
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
                  {meta.commands?.map((c) => (
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
        <div className={`mt-4 text-sm ${statusView.color}`}>
          <p>{statusView.text}</p>
          {message && <p className="mt-1 text-xs text-muted">{message}</p>}
        </div>
      )}
    </div>
  );
}
