import { Plugin } from "@/lib/types";
import { PluginCard } from "@/components/PluginCard";

export function PluginGrid({ plugins }: { plugins: Plugin[] }) {
  if (plugins.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-ink/15 bg-white/60 p-10 text-center text-ink/60">
        아직 공개된 플러그인이 없습니다.
      </div>
    );
  }

  return (
    <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      {plugins.map((plugin) => (
        <PluginCard key={plugin.id} plugin={plugin} />
      ))}
    </div>
  );
}
