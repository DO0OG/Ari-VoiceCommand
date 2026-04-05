export const MAX_PLUGIN_SIZE_BYTES = 5 * 1024 * 1024;
export const MAX_PLUGIN_SIZE_LABEL = "5MB";

export function validatePluginArchiveSize(file: File): string | null {
  if (file.size > MAX_PLUGIN_SIZE_BYTES) {
    return `ZIP 파일은 ${MAX_PLUGIN_SIZE_LABEL} 이하여야 합니다.`;
  }
  return null;
}
