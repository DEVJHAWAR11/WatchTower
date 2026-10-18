/**
 * Same-origin gateway to the Watchtower API (backend-for-frontend).
 *
 * - Attaches the access token from the httpOnly cookie, refreshing it transparently when it is about to expire
 *   or the API answers `token_expired`.
 * - Auth endpoints that return tokens have them moved into cookies and stripped from the JSON the page sees.
 * - Mutations must carry `x-wt-csrf` (a custom header cross-site forms cannot send) and a same-origin Origin.
 * - Streams responses through untouched, so Server-Sent Events work and close when the browser disconnects.
 */
import { NextResponse, type NextRequest } from "next/server";

import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  backendUrl,
  clearSession,
  refreshTokens,
  secondsLeft,
  setSession,
  type TokenSet,
} from "@/lib/server/session";


const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "idempotency-key", "last-event-id", "accept-language"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "x-request-id", "retry-after", "cache-control", "content-disposition"];
const TOKEN_ROUTES = new Set(["auth/login", "auth/signup", "auth/refresh", "auth/verify-otp"]);
const MAX_BODY = 256 * 1024;

function errorResponse(status: number, code: string, message: string) {
  return NextResponse.json({ error: { code, message } }, { status });
}

function clientIp(req: NextRequest): string | null {
  const fwd = req.headers.get("x-forwarded-for");
  return (fwd ? fwd.split(",")[0].trim() : req.headers.get("x-real-ip")) || null;
}

function sameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return req.headers.get("sec-fetch-site") !== "cross-site";
  try {
    return new URL(origin).host === (req.headers.get("x-forwarded-host") || req.headers.get("host"));
  } catch {
    return false;
  }
}

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const route = path.join("/");
  if (path.some((p) => p === ".." || p.includes("\\"))) return errorResponse(400, "bad_request", "Bad path");

  const method = req.method.toUpperCase();
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
  // Personal API tokens (Pro) may be sent directly; they are never ambient, so no CSRF check applies.
  const explicitAuth = req.headers.get("authorization");
  const apiToken = explicitAuth && /^Bearer wt_[A-Za-z0-9_-]{10,200}$/.test(explicitAuth) ? explicitAuth.slice(7) : null;
  if (mutating && !apiToken && (!req.headers.get("x-wt-csrf") || !sameOrigin(req))) {
    return errorResponse(403, "forbidden", "Cross-site request blocked");
  }

  let body: ArrayBuffer | undefined;
  if (mutating) {
    body = await req.arrayBuffer();
    if (body.byteLength > MAX_BODY) return errorResponse(413, "payload_too_large", "Request is too large");
  }

  const ip = clientIp(req);
  let access = apiToken ?? req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = apiToken ? undefined : req.cookies.get(REFRESH_COOKIE)?.value;
  let renewed: TokenSet | null = null;
  let dropSession = false;

  // Refresh slightly early so long requests (SSE) never start with a token about to lapse.
  if (refresh && secondsLeft(access) < 60 && !route.startsWith("auth/")) {
    renewed = await refreshTokens(refresh, ip);
    if (renewed) access = renewed.access_token;
    else {
      access = undefined;
      dropSession = true;
    }
  }

  const target = new URL(`${backendUrl()}/v1/${route}`);
  target.search = req.nextUrl.search;

  // Abort the upstream call when the browser goes away, including mid-stream (see the SSE wrapper below).
  const upstreamAbort = new AbortController();
  req.signal.addEventListener("abort", () => upstreamAbort.abort(), { once: true });

  const send = (token: string | undefined) => {
    const headers = new Headers();
    for (const h of FORWARD_REQUEST_HEADERS) {
      const v = req.headers.get(h);
      if (v) headers.set(h, v);
    }
    if (ip) headers.set("x-forwarded-for", ip);
    if (token) headers.set("authorization", `Bearer ${token}`);
    return fetch(target, {
      method,
      headers,
      body: body && body.byteLength ? body : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: upstreamAbort.signal,
    });
  };

  let upstream: Response;
  try {
    upstream = await send(access);
    if (upstream.status === 401 && refresh && !renewed && !route.startsWith("auth/")) {
      const err = await upstream.clone().json().catch(() => null);
      if (err?.error?.code === "token_expired" || err?.error?.code === "unauthorized") {
        renewed = await refreshTokens(refresh, ip);
        if (renewed) upstream = await send(renewed.access_token);
        else dropSession = true;
      }
    }
  } catch (e) {
    if ((e as Error)?.name === "AbortError") return new NextResponse(null, { status: 499 });
    return errorResponse(502, "upstream_unavailable", "Watchtower is temporarily unreachable. Try again shortly.");
  }

  // Token-bearing auth responses: keep the tokens server-side.
  if (TOKEN_ROUTES.has(route) && upstream.ok) {
    const data = await upstream.json().catch(() => ({}));
    const res = NextResponse.json(
      { user: data.user ?? null, message: data.message ?? null, signed_in: Boolean(data.access_token) },
      { status: upstream.status },
    );
    if (data.access_token) setSession(res, data);
    return res;
  }

  const outHeaders = new Headers();
  for (const h of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) outHeaders.set(h, v);
  }
  const isStream = upstream.headers.get("content-type")?.includes("text/event-stream");
  if (isStream) {
    outHeaders.set("cache-control", "no-cache, no-transform");
    outHeaders.set("x-accel-buffering", "no");
  }
  let responseBody: ReadableStream<Uint8Array> | null = upstream.body;
  if (isStream && upstream.body) {
    // Re-wrap so cancelling the response (tab closed, navigation) closes the API connection immediately.
    const reader = upstream.body.getReader();
    responseBody = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const { done, value } = await reader.read();
          if (done) controller.close();
          else controller.enqueue(value);
        } catch {
          controller.close();
        }
      },
      cancel() {
        upstreamAbort.abort();
        reader.cancel().catch(() => undefined);
      },
    });
  }
  const res = new NextResponse(responseBody, { status: upstream.status, headers: outHeaders });

  if (route === "auth/logout" || (route === "me" && method === "DELETE" && upstream.ok)) clearSession(res);
  else if (renewed) setSession(res, renewed);
  else if (dropSession) clearSession(res);
  return res;
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
