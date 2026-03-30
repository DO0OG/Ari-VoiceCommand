import Link from "next/link";
import { fetchPlugin } from "@/lib/api";
import { ReviewReport } from "@/components/ReviewReport";
import { InstallButton } from "@/components/InstallButton";

export default async function PluginDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const plugin = await fetchPlugin(id);

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <Link href="/marketplace" className="text-sm text-ink/60">
        ← 목록으로
      </Link>
      <section className="mt-6 rounded-[2rem] bg-white/80 p-8 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl text-ink">{plugin.name}</h1>
            <p className="mt-2 text-ink/65">
              @{plugin.developers?.github_login} · v{plugin.version}
            </p>
          </div>
          {plugin.release_url ? (
            <InstallButton pluginId={plugin.id} releaseUrl={plugin.release_url} />
          ) : null}
        </div>
        <p className="mt-5 text-lg leading-8 text-ink/75">{plugin.description}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          {(plugin.commands ?? []).map((command) => (
            <span key={command} className="rounded-full bg-fog px-3 py-1 text-sm text-ink/70">
              {command}
            </span>
          ))}
        </div>
      </section>

      <section className="mt-8 rounded-[2rem] bg-white/70 p-8 shadow-card">
        <h2 className="font-display text-2xl text-ink">설치 방법</h2>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-ink/75">
          <li>다운로드 버튼으로 ZIP 파일을 받습니다.</li>
          <li>
            압축을 풀고 Python 파일을 플러그인 경로에 복사합니다.
            <br />
            EXE 환경: %AppData%\Ari\plugins\
            <br />
            개발 환경: VoiceCommand/plugins/
          </li>
          <li>Ari를 재시작하거나 확장 탭에서 다시 적용합니다.</li>
        </ol>
      </section>

      <section className="mt-8">
        <ReviewReport report={plugin.review_report} />
      </section>
    </main>
  );
}
