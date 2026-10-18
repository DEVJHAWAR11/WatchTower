/** Public liveness summary for the status indicator: proxies the API's readiness probe without details. */
import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/server/session";

export async function GET() {
  try {
    const r = await fetch(`${backendUrl()}/readyz`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
    return NextResponse.json({ status: r.ok ? "operational" : "degraded" }, { headers: { "cache-control": "no-store" } });
  } catch {
    return NextResponse.json({ status: "unreachable" }, { headers: { "cache-control": "no-store" } });
  }
}
