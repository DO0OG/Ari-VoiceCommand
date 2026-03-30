"use client";

import { useState } from "react";
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
  if (!entry) {
    throw new Error("plugin.json 파일이 ZIP 루트에 없습니다.");
  }
  return JSON.parse(await entry.async("text"));
}

export function UploadForm() {
  const [meta, setMeta] = useState<PluginMeta | null>(null);
  const [status, setStatus] = useState<UploadState>("idle");
  const [message, setMessage] = useState("");

  async function onFileChange(file: File) {
    setStatus("idle");
    setMessage("");
    const parsed = await extractPluginJson(file);
    setMeta(parsed);
    if (parsed.api_version !== "1.0") {
      throw new Error(`api_version "${parsed.api_version}"은 지원되지 않습니다.`);
    }
  }

  async function upload(file: File) {
    setStatus("uploading");
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) {
      throw new Error("로그인이 필요합니다.");
    }

    const body = new FormData();
    body.append("plugin", file);

    const response = await fetch(
      `${process.env.NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL}/upload-plugin`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body,
      },
    );
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error ?? "업로드에 실패했습니다.");
    }

    setStatus("pending");
    setMessage(`검증이 시작되었습니다. plugin_id=${payload.plugin_id}`);
  }

  return (
    <div className="rounded-3xl bg-white p-6 shadow-card">
      <h2 className="font-display text-2xl text-ink">플러그인 업로드</h2>
      <label className="mt-5 flex cursor-pointer flex-col items-center justify-center rounded-3xl border border-dashed border-ink/20 bg-fog p-10 text-center">
        <span className="text-ink">ZIP 파일을 선택하세요</span>
        <input
          type="file"
          accept=".zip"
          className="hidden"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) {
              return;
            }
            try {
              await onFileChange(file);
              await upload(file);
            } catch (error) {
              setStatus("error");
              setMessage(error instanceof Error ? error.message : "업로드 실패");
            }
          }}
        />
      </label>

      {meta ? (
        <div className="mt-5 rounded-2xl border border-ink/10 p-4 text-sm text-ink/75">
          <p>이름: {meta.name}</p>
          <p>버전: {meta.version}</p>
          <p>엔트리: {meta.entry}</p>
          <p>권한: {(meta.permissions ?? []).join(", ") || "없음"}</p>
        </div>
      ) : null}

      {status !== "idle" ? (
        <p className="mt-4 text-sm text-ink/70">
          상태: <strong>{status}</strong> {message ? `- ${message}` : ""}
        </p>
      ) : null}
    </div>
  );
}
