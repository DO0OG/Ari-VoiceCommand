"use client";

import { supabase } from "@/lib/supabase";

export type PluginInstallTrackingResult = {
  tracked: boolean;
  message?: string;
};

async function extractInvokeErrorMessage(error: { message?: string; context?: unknown }): Promise<string> {
  let message = error.message ?? "설치 기록을 저장하지 못했습니다.";
  try {
    if (error.context instanceof Response) {
      const payload = await error.context.clone().json();
      message = payload.error ?? payload.message ?? message;
    }
  } catch {
    // 기본 메시지 유지
  }
  return message;
}

export async function trackPluginInstall(pluginId: string): Promise<PluginInstallTrackingResult> {
  const { error } = await supabase.functions.invoke("install-plugin", {
    body: { plugin_id: pluginId },
  });

  if (error) {
    const message = await extractInvokeErrorMessage(error as { message?: string; context?: unknown });
    console.error("[Marketplace] install-plugin 호출 실패:", message);
    return { tracked: false, message };
  }

  return { tracked: true };
}
