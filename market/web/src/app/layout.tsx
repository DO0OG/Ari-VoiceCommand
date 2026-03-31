import type { Metadata } from "next";
import "@/app/globals.css";
import { AuthProvider } from "@/components/AuthProvider";
import { Navbar } from "@/components/Navbar";

export const metadata: Metadata = {
  title: "Ari Marketplace",
  description: "Ari 플러그인 마켓플레이스",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <AuthProvider>
          <Navbar />
          <main>{children}</main>
          <footer className="mx-auto flex max-w-6xl justify-end px-6 py-5 text-xs text-white/45">
            <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1">
              Web UI refresh check · 2026-03-31
            </span>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
