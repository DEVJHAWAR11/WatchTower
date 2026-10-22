"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Binoculars,
  ChevronDown,
  Home,
  LogOut,
  Plus,
  Search,
  Settings,
  Shield,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { CategoryArt } from "@/components/art/category";
import { Logo } from "@/components/art/logo";
import { ObservatoryScene } from "@/components/art/observatory";
import { Topo } from "@/components/art/topo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Crosshair, Kicker } from "@/components/ui/display";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/primitives";
import { api, setUnauthorizedHandler } from "@/lib/api";
import { useDashboard, useMe } from "@/lib/queries";
import { StreamProvider, useStream } from "@/lib/stream";
import type { Alert, Page } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEEN_KEY = "wt:alerts-seen-at";

export function readSeenAt(): number {
  try {
    return Number(localStorage.getItem(SEEN_KEY) || 0);
  } catch {
    return 0;
  }
}
export function markAlertsSeen() {
  try {
    localStorage.setItem(SEEN_KEY, String(Date.now()));
    window.dispatchEvent(new Event("wt:alerts-seen"));
  } catch {
    /* storage unavailable: unread badge just won't persist */
  }
}

function subscribeSeen(cb: () => void) {
  window.addEventListener("wt:alerts-seen", cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener("wt:alerts-seen", cb);
    window.removeEventListener("storage", cb);
  };
}

function useUnreadAlerts() {
  const seen = useSyncExternalStore(subscribeSeen, readSeenAt, () => Number.MAX_SAFE_INTEGER);
  const q = useQuery({
    queryKey: ["alerts", "badge"],
    queryFn: () => api<Page<Alert>>("alerts", { query: { limit: 20 } }),
    staleTime: 30_000,
  });
  return (q.data?.items ?? []).filter((a) => new Date(a.created_at).getTime() > seen).length;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    setUnauthorizedHandler(() => router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  return (
    <StreamProvider>
      <div className="min-h-dvh lg:grid lg:grid-cols-[260px_minmax(0,1fr)]">
        <Sidebar pathname={pathname} />
        <div className="flex min-h-dvh min-w-0 flex-col overflow-x-clip">
          <TopBar pathname={pathname} />
          <main id="main" className="relative flex-1 pb-28 lg:pb-16">
            {children}
          </main>
        </div>
        <MobileNav pathname={pathname} />
      </div>
    </StreamProvider>
  );
}

function useNav() {
  const me = useMe();
  const dash = useDashboard();
  const unread = useUnreadAlerts();
  return useMemo(() => {
    const items = [
      { href: "/dashboard", label: "My watches", icon: Binoculars, count: dash.data?.totals.watches, match: ["/dashboard", "/watches"] },
      { href: "/community", label: "Community", icon: Users, match: ["/community"] },
      { href: "/alerts", label: "Alerts", icon: Bell, dot: unread, match: ["/alerts"] },
      { href: "/settings", label: "Settings", icon: Settings, match: ["/settings"] },
    ];
    if (me.data?.role === "admin") items.push({ href: "/admin", label: "Admin", icon: Shield, match: ["/admin"] });
    return items;
  }, [me.data?.role, dash.data?.totals.watches, unread]);
}

function Sidebar({ pathname }: { pathname: string }) {
  const nav = useNav();
  return (
    <aside className="sticky top-0 hidden h-dvh flex-col overflow-hidden border-r border-line lg:flex">
      <div className="flex h-[88px] items-center border-b border-line px-7">
        <Logo href="/dashboard" />
      </div>
      <nav aria-label="App" className="mt-5 flex flex-col">
        {nav.map((n) => {
          const active = n.match.some((m) => pathname === m || pathname.startsWith(`${m}/`));
          return (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-4 px-7 py-3.5 text-[16px] transition-colors",
                active ? "bg-sunken text-ink before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-ink dark:before:bg-amber" : "text-ink-2 hover:bg-sunken/60 hover:text-ink",
              )}
            >
              <n.icon className="h-[22px] w-[22px]" strokeWidth={1.5} aria-hidden />
              <span className="flex-1">{n.label}</span>
              {"count" in n && n.count !== undefined && <span className="text-sm text-ink-3">{n.count}</span>}
              {"dot" in n && n.dot ? (
                <span className="flex items-center gap-2 text-sm text-ink-2">
                  <span className="h-2 w-2 rounded-full bg-amber" aria-hidden />
                  <span className="sr-only">unread:</span>
                  {n.dot}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>
      <div className="px-6 pt-8">
        <Link
          href="/watches/new"
          className="flex items-center justify-center gap-2 border border-dashed border-line-strong py-3 text-sm text-ink-2 transition-colors hover:border-ink hover:text-ink"
        >
          <Plus className="h-4 w-4" /> New watch
        </Link>
      </div>
      <div className="relative mt-auto h-[46%] min-h-[260px]">
        <Crosshair className="absolute right-8 top-2" />
        <Kicker className="absolute left-7 top-10" lines={["// monitor", "// analyze", "// alert", "// stay ahead"]} />
        <div className="absolute inset-x-0 bottom-0 h-[78%] [mask-image:linear-gradient(to_bottom,transparent,black_30%)]">
          <ObservatoryScene parallax={false} glow={false} />
        </div>
      </div>
    </aside>
  );
}

const CRUMBS: Record<string, string> = {
  dashboard: "Dashboard",
  watches: "My watches",
  new: "New watch",
  alerts: "Alerts",
  community: "Community",
  settings: "Settings",
  admin: "Admin",
};

function TopBar({ pathname }: { pathname: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const stream = useStream();
  const [q, setQ] = useState("");
  const parts = pathname.split("/").filter(Boolean);
  const crumbs = parts
    .map((p) => CRUMBS[p])
    .filter(Boolean)
    .slice(0, 2);
  const name = me.data?.display_name || me.data?.handle || me.data?.email?.split("@")[0] || "";
  const initial = (name[0] || "·").toUpperCase();

  const signOut = async () => {
    try {
      await api("auth/logout", { method: "POST" });
    } catch {
      /* cookies are cleared by the gateway either way */
    }
    qc.clear();
    router.replace("/");
    router.refresh();
  };

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/90 backdrop-blur-md">
      <div className="flex h-16 items-center gap-4 px-4 sm:px-6 lg:h-[88px] lg:px-10">
        <span className="lg:hidden">
          <Logo href="/dashboard" compact />
        </span>
        <nav aria-label="Breadcrumb" className="label-mono hidden min-w-0 items-center gap-2 truncate text-ink-2 md:flex">
          <span aria-hidden>/</span>
          {crumbs.map((c, i) => (
            <span key={c} className="flex items-center gap-2">
              {i > 0 && <span aria-hidden>/</span>}
              {c}
            </span>
          ))}
          <span className="ml-1 text-ink-3" aria-hidden>
            ··
          </span>
        </nav>
        <form
          role="search"
          className="relative mx-auto hidden w-full max-w-md md:block"
          onSubmit={(e) => {
            e.preventDefault();
            router.push(`/dashboard?q=${encodeURIComponent(q.trim())}`);
          }}
        >
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search your watches…"
            aria-label="Search your watches"
            className="h-11 w-full border border-line-strong/70 bg-elevated/70 pl-10 pr-3 text-[15px] text-ink placeholder:text-ink-3 focus-visible:border-ink focus-visible:outline-none"
          />
        </form>
        <div className="ml-auto flex items-center gap-3 md:ml-0">
          <div className="hidden items-center gap-4 border-l border-line pl-6 2xl:flex">
            <div className="label-mono whitespace-nowrap text-[10px] leading-[1.7] text-ink-2">
              Global monitoring
              <br />
              Real-time signals
              <br />
              <span className="inline-flex items-center gap-1.5">
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    stream?.status === "live" ? "bg-ok-dot" : stream?.status === "connecting" ? "bg-amber" : "bg-err-dot",
                  )}
                  aria-hidden
                />
                {stream?.status === "live" ? "Live" : stream?.status === "connecting" ? "Connecting" : "Offline"}
              </span>
            </div>
            <CategoryArt slug="events" seed="topbar" className="h-14 w-24 border border-line grayscale" />
          </div>
          <Link href="/alerts" className="relative grid h-10 w-10 place-items-center text-ink-2 hover:text-ink lg:hidden" aria-label="Alerts">
            <Bell className="h-5 w-5" />
          </Link>
          <Menu>
            <MenuTrigger className="flex items-center gap-2.5 rounded-[3px] py-1 pl-1 pr-2 text-ink hover:bg-sunken" aria-label="Account menu">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-ink-3/30 font-medium text-ink">{initial}</span>
              <span className="hidden max-w-[120px] truncate text-[15px] sm:block">{name || " "}</span>
              <ChevronDown className="hidden h-4 w-4 text-ink-3 sm:block" aria-hidden />
            </MenuTrigger>
            <MenuContent>
              <MenuLabel>{me.data?.email || "Account"}</MenuLabel>
              <MenuItem icon={<Settings />} onSelect={() => router.push("/settings")}>
                Settings
              </MenuItem>
              <MenuItem icon={<Home />} onSelect={() => router.push("/")}>
                Website
              </MenuItem>
              <MenuSeparator />
              <div className="flex items-center justify-between px-2.5 py-2">
                <span className="text-sm text-ink-2">Theme</span>
                <ThemeToggle />
              </div>
              <MenuSeparator />
              <MenuItem icon={<LogOut />} onSelect={signOut}>
                Sign out
              </MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>
    </header>
  );
}

function MobileNav({ pathname }: { pathname: string }) {
  const nav = useNav().filter((n) => n.href !== "/admin");
  const items = [{ ...nav[0], label: "Home", icon: Home }, ...nav.slice(1)];
  return (
    <nav aria-label="App" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/95 backdrop-blur-md lg:hidden">
      <div className="relative mx-auto flex max-w-xl items-stretch justify-around px-2 pb-[max(env(safe-area-inset-bottom),0.5rem)] pt-2">
        {items.map((n) => {
          const active = n.match.some((m) => pathname === m || pathname.startsWith(`${m}/`)) && !(n.href === "/dashboard" && pathname === "/watches/new");
          return (
            <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined} className={cn("relative flex w-16 flex-col items-center gap-1 py-1 text-[11px]", active ? "text-amber-ink" : "text-ink-3")}>
              <n.icon className="h-6 w-6" strokeWidth={1.5} aria-hidden />
              {n.label}
              {"dot" in n && n.dot ? <span className="absolute right-4 top-0 h-2 w-2 rounded-full bg-amber" aria-label={`${n.dot} unread`} /> : null}
            </Link>
          );
        })}
        {pathname === "/dashboard" && (
        <Link
          href="/watches/new"
          aria-label="New watch"
          className="absolute bottom-full right-4 mb-3 grid h-14 w-14 place-items-center rounded-full bg-amber text-on-amber shadow-float transition-transform active:scale-95"
        >
          <Plus className="h-6 w-6" />
        </Link>
        )}
      </div>
    </nav>
  );
}

/** Shared page header: "[01] LABEL", big serif title, actions. */
export function PageHeader({
  kicker,
  title,
  subtitle,
  actions,
  className,
}: {
  kicker?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          {kicker && <div className="label-mono mb-4 text-ink-3">{kicker}</div>}
          <h1 className="font-display text-[clamp(2.3rem,4.6vw,3.9rem)] leading-[0.98] text-ink">{title}</h1>
          {subtitle && <p className="mt-3 max-w-2xl text-[16px] text-ink-2">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function PageFrame({ children, className, topo = true }: { children: React.ReactNode; className?: string; topo?: boolean }) {
  return (
    <div className={cn("relative", className)}>
      {topo && <Topo className="h-[420px] opacity-70" />}
      <div className="relative mx-auto max-w-[1400px] px-4 pt-8 sm:px-6 lg:px-10 lg:pt-12">{children}</div>
    </div>
  );
}
