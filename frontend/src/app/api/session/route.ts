/** Adopt a session that arrived in a URL fragment (Google OAuth, magic links, password recovery). */
import { NextResponse, type NextRequest } from "next/server";

import { backendUrl, setSession } from "@/lib/server/session";


export async function POST(req: NextRequest) {
  const origin = req.headers.get("origin");
  if (!req.headers.get("x-wt-csrf") || (origin && new URL(origin).host !== req.headers.get("host"))) {
    return NextResponse.json({ error: { code: "forbidden", message: "Cross-site request blocked" } }, { status: 403 });
  }
  const body = await req.json().catch(() => null);
  const access = typeof body?.access_token === "string" ? body.access_token : "";
  const refresh = typeof body?.refresh_token === "string" ? body.refresh_token : "";
  if (!access || access.length > 8192 || refresh.length > 4096) {
    return NextResponse.json({ error: { code: "invalid", message: "Missing session" } }, { status: 400 });
  }
  // Only keep tokens the API itself accepts.
  const me = await fetch(`${backendUrl()}/v1/me`, { headers: { authorization: `Bearer ${access}` }, cache: "no-store" });
  if (!me.ok) {
    return NextResponse.json({ error: { code: "unauthorized", message: "That sign-in link is no longer valid." } },
      { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  setSession(res, { access_token: access, refresh_token: refresh || null, expires_in: Number(body.expires_in) || null });
  return res;
}
