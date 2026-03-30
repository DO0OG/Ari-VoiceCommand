"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";
import { signInWithGitHub, supabase } from "@/lib/supabase";

export function Navbar() {
  const { session, loading } = useAuth();

  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-[#09090f]/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/marketplace" className="flex items-center gap-2.5">
          <span className="text-xl font-bold tracking-tight">
            <span className="gradient-text">Ari</span>
            <span className="text-subtle ml-1 font-medium">Marketplace</span>
          </span>
        </Link>

        <nav className="flex items-center gap-4">
          <Link
            href="/marketplace"
            className="text-sm text-subtle transition hover:text-bright"
          >
            플러그인
          </Link>
          {session && (
            <Link
              href="/dashboard"
              className="text-sm text-subtle transition hover:text-bright"
            >
              대시보드
            </Link>
          )}
          {!loading && (
            session ? (
              <button
                onClick={() => supabase.auth.signOut()}
                className="rounded-lg border border-white/10 px-3.5 py-1.5 text-sm text-subtle transition hover:border-white/20 hover:text-bright"
              >
                로그아웃
              </button>
            ) : (
              <button
                onClick={() => signInWithGitHub()}
                className="rounded-lg bg-gradient-to-r from-accent to-accent-2 px-4 py-1.5 text-sm font-medium text-white shadow-glow transition hover:opacity-90"
              >
                GitHub 로그인
              </button>
            )
          )}
        </nav>
      </div>
    </header>
  );
}
