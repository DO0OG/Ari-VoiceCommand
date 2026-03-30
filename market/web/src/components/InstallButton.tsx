"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase";

export function InstallButton({
  pluginId,
  releaseUrl,
}: {
  pluginId: string;
  releaseUrl: string;
}) {
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");

  async function handleInstall() {
    setState("loading");
    try {
      await supabase.functions.invoke("install-plugin", {
        body: { plugin_id: pluginId },
      });
    } catch { /* 카운트 실패해도 다운로드는 진행 */ }
    window.open(releaseUrl, "_blank");
    setState("done");
  }

  return (
    <button
      onClick={handleInstall}
      disabled={state === "loading"}
      className="rounded-full bg-accent px-6 py-3 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
    >
      {state === "loading" ? "처리 중..." : state === "done" ? "✓ 다운로드됨" : "다운로드"}
    </button>
  );
}
