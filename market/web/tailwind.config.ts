import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        base: "#09090f",
        surface: "rgba(255,255,255,0.04)",
        muted: "#64748b",
        subtle: "#94a3b8",
        bright: "#f1f5f9",
        accent: "#7c3aed",
        "accent-2": "#3b82f6",
        "tag-bg": "rgba(124,58,237,0.15)",
        "tag-text": "#a78bfa",
        "badge-bg": "rgba(34,197,94,0.12)",
        "badge-text": "#4ade80",
      },
      fontFamily: {
        sans: ["Pretendard", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.06) inset, 0 8px 32px rgba(0,0,0,0.4)",
        glow: "0 0 24px rgba(124,58,237,0.35)",
      },
    },
  },
  plugins: [],
};

export default config;
