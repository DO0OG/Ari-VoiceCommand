import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        fog: "#f2efe8",
        ember: "#d97706",
        pine: "#135c52",
      },
      fontFamily: {
        display: ["Georgia", "serif"],
        body: ["'Segoe UI'", "sans-serif"],
      },
      boxShadow: {
        card: "0 18px 55px rgba(17, 24, 39, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
