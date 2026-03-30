import Link from "next/link";
import { Plugin } from "@/lib/types";

export function PluginCard({ plugin }: { plugin: Plugin }) {
  return (
    <Link
      href={`/marketplace/${plugin.id}`}
      className="glass group flex flex-col rounded-2xl p-5 shadow-card transition duration-200 hover:-translate-y-0.5 hover:border-white/[0.14] hover:shadow-glow"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-bright">{plugin.name}</p>
          <p className="mt-0.5 text-xs text-muted">v{plugin.version}</p>
        </div>
        <span className="shrink-0 rounded-full bg-[rgba(34,197,94,0.12)] px-2.5 py-1 text-[11px] font-medium text-[#4ade80]">
          검증 완료
        </span>
      </div>

      <p className="mt-3 line-clamp-2 grow text-sm leading-6 text-subtle">
        {plugin.description}
      </p>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {(plugin.commands ?? []).slice(0, 4).map((cmd) => (
          <span
            key={cmd}
            className="rounded-full bg-[rgba(124,58,237,0.15)] px-2.5 py-0.5 text-[11px] text-[#a78bfa]"
          >
            {cmd}
          </span>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-4 w-4 rounded-full bg-white/10 text-center leading-4">@</span>
          {plugin.developers?.github_login ?? "unknown"}
        </span>
        <span>↓ {plugin.install_count.toLocaleString()}</span>
      </div>
    </Link>
  );
}
