"use client";

import { useState } from "react";
import { trackPluginInstall } from "@/lib/pluginInstall";

export function InstallButton({
  pluginId,
  releaseUrl,
}: {
  pluginId: string;
  releaseUrl: string;
}) {
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const [note, setNote] = useState("");

  async function handleInstall() {
    setState("loading");
    setNote("");
    const result = await trackPluginInstall(pluginId);
    if (!result.tracked) {
      setNote(result.message ?? "다운로드는 시작했지만 설치 기록 저장에는 실패했습니다.");
    }
    window.open(releaseUrl, "_blank");
    setState("done");
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        onClick={() => { void handleInstall(); }}
        disabled={state === "loading"}
        className="rounded-full bg-accent px-6 py-3 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
      >
        {state === "loading" ? "처리 중..." : state === "done" ? "✓ 다운로드됨" : "다운로드"}
      </button>
      {note ? <p className="text-xs text-amber-700">{note}</p> : null}
    </div>
  );
}
