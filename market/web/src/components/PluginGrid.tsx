import { Plugin } from "@/lib/types";
import { PluginCard } from "@/components/PluginCard";

export function PluginGrid({ plugins }: { plugins: Plugin[] }) {
  if (plugins.length === 0) {
    return (
      <div className="glass rounded-2xl p-16 text-center text-subtle">
        <p className="text-4xl">🔌</p>
        <p className="mt-4 text-sm">아직 공개된 플러그인이 없습니다.</p>
        <p className="mt-1 text-xs text-muted">첫 번째 플러그인을 등록해보세요.</p>
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {plugins.map((plugin) => (
        <PluginCard key={plugin.id} plugin={plugin} />
      ))}
    </div>
  );
}
