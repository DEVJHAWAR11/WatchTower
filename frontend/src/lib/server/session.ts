import "server-only";

import type { NextResponse } from "next/server";

/** Session tokens live only in httpOnly cookies: page scripts never see them, so XSS cannot steal a session. */
export const ACCESS_COOKIE = "wt_at";
export const REFRESH_COOKIE = "wt_rt";
/** Non-secret hint for client code ("someone is signed in"); holds no token. */
export const HINT_COOKIE = "wt_s";

const REFRESH_MAX_AGE = 60 * 60 * 24 * 30;
const secure = process.env.NODE_ENV === "production";

export function backendUrl(): string {
  return (process.env.WT_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

export interface TokenSet {
  access_token: string;
  refresh_token?: string | null;
  expires_in?: number | null;
}

/** Seconds until the JWT expires (no signature check: the backend verifies; this only schedules refreshes). */
export function secondsLeft(jwt: string | undefined): number {
  if (!jwt) return -1;
  try {
    const payload = JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString("utf8"));
    return typeof payload.exp === "number" ? payload.exp - Math.floor(Date.now() / 1000) : -1;
  } catch {
    return -1;
  }
}

export function setSession(res: NextResponse, t: TokenSet): void {
  const ttl = Math.max(60, Math.min(t.expires_in ?? secondsLeft(t.access_token), 60 * 60 * 24));
  const base = { httpOnly: true, secure, sameSite: "lax" as const, path: "/" };
  res.cookies.set(ACCESS_COOKIE, t.access_token, { ...base, maxAge: ttl });
  if (t.refresh_token) res.cookies.set(REFRESH_COOKIE, t.refresh_token, { ...base, maxAge: REFRESH_MAX_AGE });
  res.cookies.set(HINT_COOKIE, "1", { httpOnly: false, secure, sameSite: "lax", path: "/", maxAge: REFRESH_MAX_AGE });
}

export function clearSession(res: NextResponse): void {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, HINT_COOKIE]) {
    res.cookies.set(name, "", { path: "/", maxAge: 0 });
  }
}

/** Exchange a refresh token for a new session. Returns null when the refresh token is no longer valid. */
export async function refreshTokens(refreshToken: string, forwardedFor?: string | null): Promise<TokenSet | null> {
  try {
    const r = await fetch(`${backendUrl()}/v1/auth/refresh`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(forwardedFor ? { "x-forwarded-for": forwardedFor } : {}),
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (!r.ok) return null;
    const data = await r.json();
    return data?.access_token ? data : null;
  } catch {
    return null;
  }
}
