import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  if (!code) {
    return NextResponse.redirect(new URL("/dashboard?error=missing_code", request.url));
  }

  const callbackUrl = new URL(
    `${process.env.NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL}/auth-callback`,
  );
  callbackUrl.searchParams.set("code", code);
  return NextResponse.redirect(callbackUrl);
}
