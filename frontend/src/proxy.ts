import { NextResponse, type NextRequest } from "next/server";

// Optimistic routing only: the API verifies every request, this just avoids flashing app pages to signed-out users.
const APP_PREFIXES = ["/dashboard", "/watches", "/alerts", "/community", "/settings", "/admin"];
const GUEST_ONLY = ["/login", "/signup"];

export function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const signedIn = req.cookies.has("wt_rt") || req.cookies.has("wt_at");

  if (!signedIn && APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  if (signedIn && GUEST_ONLY.includes(pathname)) {
    const url = req.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/watches/:path*", "/alerts/:path*", "/community/:path*", "/settings/:path*", "/admin/:path*", "/login", "/signup"],
};
