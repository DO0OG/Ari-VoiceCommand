export type PluginReviewStage = {
  passed: boolean;
  detail?: unknown;
};

export type PluginReviewReport = {
  status?: "approved" | "rejected" | "pending";
  summary?: string;
  stages?: Record<string, PluginReviewStage>;
};

export type Plugin = {
  id: string;
  name: string;
  version: string;
  api_version?: string;
  description: string;
  commands?: string[];
  permissions?: string[];
  entry?: string;
  status?: "pending" | "approved" | "rejected";
  install_count: number;
  created_at: string;
  reviewed_at?: string;
  release_url?: string;
  sha256?: string;
  review_report?: PluginReviewReport;
  developers?: {
    github_login?: string;
    email?: string;
  };
};
