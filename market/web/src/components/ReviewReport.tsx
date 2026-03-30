import { PluginReviewReport } from "@/lib/types";

const LABELS: Record<string, string> = {
  virus_scan: "바이러스 스캔 (ClamAV)",
  static_analysis: "정적 분석 (bandit + pylint)",
  semgrep_review: "semgrep 보안 스캔",
};

export function ReviewReport({ report }: { report?: PluginReviewReport }) {
  const stages = report?.stages ?? {};

  return (
    <div className="rounded-3xl bg-white p-6 shadow-card">
      <h2 className="font-display text-2xl text-ink">검증 리포트</h2>
      <div className="mt-4 space-y-4">
        {Object.entries(stages).map(([key, value], index) => (
          <div key={key} className="rounded-2xl border border-ink/10 p-4">
            <p className="font-medium text-ink">
              {index + 1}. {LABELS[key] ?? key}
            </p>
            <p className={`mt-2 text-sm ${value.passed ? "text-pine" : "text-red-600"}`}>
              {value.passed ? "통과" : "실패"}
            </p>
            {!value.passed && value.detail ? (
              <pre className="mt-3 overflow-x-auto rounded-2xl bg-ink p-4 text-xs text-white">
                {JSON.stringify(value.detail, null, 2)}
              </pre>
            ) : null}
          </div>
        ))}
      </div>
      {report?.summary ? <p className="mt-4 text-sm text-ink/70">{report.summary}</p> : null}
    </div>
  );
}
