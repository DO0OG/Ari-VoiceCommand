import Link from "next/link";
import { Plugin } from "@/lib/types";

export function PluginCard({ plugin }: { plugin: Plugin }) {
  return (
    <Link
      href={`/marketplace/${plugin.id}`}
      className="group rounded-3xl border border-black/5 bg-white/85 p-5 shadow-card transition hover:-translate-y-1 hover:shadow-2xl"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-display text-xl text-ink">{plugin.name}</p>
          <p className="text-sm text-ink/55">v{plugin.version}</p>
        </div>
        <span className="rounded-full bg-pine/10 px-3 py-1 text-xs font-semibold text-pine">
          검증 완료
        </span>
      </div>
      <p className="mt-3 line-clamp-2 text-sm leading-6 text-ink/75">{plugin.description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {(plugin.commands ?? []).slice(0, 4).map((command) => (
          <span key={command} className="rounded-full bg-fog px-3 py-1 text-xs text-ink/70">
            {command}
          </span>
        ))}
      </div>
      <div className="mt-5 flex items-center justify-between text-sm text-ink/50">
        <span>@{plugin.developers?.github_login ?? "unknown"}</span>
        <span>설치 {plugin.install_count.toLocaleString()}</span>
      </div>
    </Link>
  );
}
