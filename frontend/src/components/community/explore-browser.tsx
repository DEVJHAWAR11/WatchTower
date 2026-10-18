"use client";

import { ArrowRight, Flame, LayoutGrid, List, Plus, Search, Users } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { CategoryIcon, categoryOf } from "@/components/art/category";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SectionLabel } from "@/components/ui/display";
import { NativeSelect } from "@/components/ui/field";
import { useCategories, useExplore, useMyWatches } from "@/lib/queries";
import type { Category, ExplorePage, PublicWatch } from "@/lib/types";
import { useSignedIn } from "@/lib/use-session";
import { cn, compactNumber, relativeTime } from "@/lib/utils";

import { SubscribeButton, WatchCard, WatchCardSkeleton } from "./watch-card";

const SORTS = [
  { v: "trending", label: "Trending" },
  { v: "popular", label: "Most subscribed" },
  { v: "recently_fired", label: "Recently fired" },
  { v: "new", label: "Newest" },
];

export function ExploreBrowser({
  initial,
  initialCategories,
  hrefBase = "/explore",
}: {
  initial?: ExplorePage | null;
  initialCategories?: Category[] | null;
  hrefBase?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const sort = sp.get("sort") || "trending";
  const category = sp.get("category") || "";
  const q = sp.get("q") || "";
  const [query, setQuery] = useState(q);
  const [view, setView] = useState<"grid" | "list">("grid");
  const searchRef = useRef<HTMLInputElement>(null);
  const signedIn = useSignedIn();
  const mine = useMyWatches("all", Boolean(signedIn));
  const subscribed = useMemo(() => new Set((mine.data ?? []).map((w) => w.id)), [mine.data]);

  const setParam = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    router.replace(`${pathname}${next.toString() ? `?${next}` : ""}`, { scroll: false });
  };

  // debounce typing into the URL
  useEffect(() => {
    if (query === q) return;
    const t = setTimeout(() => setParam({ q: query.trim() }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  // ⌘K / Ctrl+K focuses search
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const params = { sort, category: category || undefined, q: q || undefined };
  const isDefault = sort === "trending" && !category && !q;
  const list = useExplore(params);
  const trending = useExplore({ sort: "trending" });
  const cats = useCategories();
  const categories = cats.data ?? initialCategories ?? [];

  const items: PublicWatch[] = list.data
    ? list.data.pages.flatMap((p) => p.items)
    : isDefault && initial
      ? initial.items
      : [];
  const top = (trending.data?.pages[0]?.items ?? (initial?.items || [])).slice(0, 4);
  const loading = list.isPending && !(isDefault && initial);

  return (
    <div>
      {/* search + filters */}
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative flex-1">
          <span className="sr-only">Search community watches</span>
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-3" aria-hidden />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search watches, topics or creators…"
            className="h-12 w-full border border-line-strong/80 bg-elevated pl-12 pr-16 text-[15px] text-ink placeholder:text-ink-3 focus-visible:border-ink focus-visible:outline-none"
            type="search"
          />
          <kbd className="label-mono absolute right-3 top-1/2 hidden -translate-y-1/2 border border-line px-1.5 py-0.5 text-[10px] text-ink-3 sm:block">⌘ K</kbd>
        </label>
        <div className="sm:w-56">
          <NativeSelect aria-label="Sort watches" value={sort} onChange={(e) => setParam({ sort: e.target.value === "trending" ? "" : e.target.value })} className="h-12">
            {SORTS.map((s) => (
              <option key={s.v} value={s.v}>
                {s.label}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      <div className="scrollbar-none -mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="toolbar" aria-label="Filter by category">
        {[{ slug: "", name: "All" }, ...categories.filter((c) => c.slug !== "other")].map((c) => {
          const active = category === c.slug;
          return (
            <button
              key={c.slug || "all"}
              onClick={() => setParam({ category: c.slug })}
              aria-pressed={active}
              className={cn(
                "shrink-0 whitespace-nowrap rounded-[3px] border px-4 py-2 text-sm transition-colors",
                active ? "border-ink bg-ink text-bg" : "border-line-strong/70 text-ink-2 hover:border-ink hover:text-ink",
              )}
            >
              {c.slug ? categoryOf(c.slug).label : "All"}
            </button>
          );
        })}
      </div>

      {/* trending row */}
      {isDefault && top.length >= 2 && (
        <section className="mt-12" aria-labelledby="trending-title">
          <SectionLabel index={1} as="h2">
            <span id="trending-title">Trending this week</span>
          </SectionLabel>
          <ol className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {top.map((w, k) => (
              <motion.li key={w.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * 0.06 }}>
                <Link
                  href={`${hrefBase}/${w.slug}`}
                  className={cn(
                    "ticked group flex h-full gap-4 border p-5 transition-colors",
                    k === 0 ? "border-amber/70 bg-amber-soft/50" : "border-line bg-elevated/60 hover:border-line-strong",
                  )}
                >
                  <span className="font-display text-4xl leading-none text-accent-display">{k + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="label-mono text-[10px] text-ink-3">{categoryOf(w.category_slug, w.kind).label} ↗</span>
                    <span className="mt-1 block font-display text-[21px] leading-tight text-ink group-hover:underline group-hover:decoration-1 group-hover:underline-offset-4">
                      {w.title}
                    </span>
                    <span className="mt-3 flex items-center gap-1.5 text-[13px] text-ink-2">
                      <Flame className="h-3.5 w-3.5 text-amber-ink" aria-hidden /> {compactNumber(w.subscriber_count)} subscribers
                    </span>
                  </span>
                </Link>
              </motion.li>
            ))}
          </ol>
        </section>
      )}

      {/* all watches */}
      <section className="mt-12" aria-labelledby="all-title">
        <div className="flex items-end justify-between gap-4">
          <SectionLabel index={isDefault && top.length >= 2 ? 2 : 1} as="h2">
            <span id="all-title">{q ? `Results for “${q}”` : category ? categoryOf(category).label : "All watches"}</span>
          </SectionLabel>
          <div className="hidden border border-line-strong p-0.5 sm:flex" role="radiogroup" aria-label="Layout">
            {(
              [
                ["grid", LayoutGrid, "Grid"],
                ["list", List, "List"],
              ] as const
            ).map(([v, Icon, label]) => (
              <button
                key={v}
                role="radio"
                aria-checked={view === v}
                onClick={() => setView(v)}
                className={cn("flex items-center gap-2 px-3 py-1.5 text-sm", view === v ? "bg-ink text-bg" : "text-ink-2 hover:text-ink")}
              >
                <Icon className="h-4 w-4" aria-hidden /> {label}
              </button>
            ))}
          </div>
        </div>

        {list.isError ? (
          <ErrorState className="mt-6" error={list.error} onRetry={() => list.refetch()} />
        ) : loading ? (
          <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }, (_, i) => (
              <WatchCardSkeleton key={i} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<Search />}
            title={q || category ? "Nothing matches yet" : "No community watches yet"}
            body={
              q || category
                ? "Try another word or category, or create the watch yourself and publish it for others."
                : "Create a watch and make it public. Once it's approved, others can subscribe."
            }
            action={
              <Button asChild mono>
                <Link href={signedIn ? "/watches/new" : "/signup"}>
                  <Plus className="h-4 w-4" /> Create a watch
                </Link>
              </Button>
            }
          />
        ) : view === "grid" ? (
          <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {items.map((w) => (
              <WatchCard key={w.id} watch={w} layout="compact" subscribed={subscribed.has(w.id)} hrefBase={hrefBase} />
            ))}
          </div>
        ) : (
          <ul className="mt-6 divide-y divide-line border-y border-line">
            {items.map((w) => (
              <li key={w.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:gap-6">
                <CategoryIcon slug={w.category_slug} kind={w.kind} className="hidden h-5 w-5 text-ink-2 sm:block" />
                <div className="min-w-0 flex-1">
                  <Link href={`${hrefBase}/${w.slug}`} className="font-display text-xl text-ink hover:underline hover:underline-offset-4">
                    {w.title}
                  </Link>
                  {w.description && <p className="line-clamp-1 text-sm text-ink-2">{w.description}</p>}
                </div>
                <div className="flex items-center gap-6 text-sm text-ink-2">
                  <span className="flex items-center gap-1.5">
                    <Users className="h-4 w-4 text-ink-3" aria-hidden /> {compactNumber(w.subscriber_count)}
                  </span>
                  <span className="w-28 text-ink-3">{w.last_alert_at ? `Fired ${relativeTime(w.last_alert_at)}` : "Not fired yet"}</span>
                  <SubscribeButton watch={w} subscribed={subscribed.has(w.id)} />
                </div>
              </li>
            ))}
          </ul>
        )}

        {list.hasNextPage && (
          <div className="mt-10 flex justify-center">
            <Button variant="outline" mono onClick={() => list.fetchNextPage()} loading={list.isFetchingNextPage}>
              Load more <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}
