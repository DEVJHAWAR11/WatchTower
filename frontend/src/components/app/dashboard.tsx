"use client";

import { ArrowRight, Bell, Binoculars, CircleCheck, Database, Plus, Search, Sparkles, Zap } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { CategoryIcon } from "@/components/art/category";
import { Button } from "@/components/ui/button";
import { Badge, Crosshair, ErrorState, Kicker, Skeleton, Sparkbars, StatusDot } from "@/components/ui/display";
import { NativeSelect } from "@/components/ui/field";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { useDashboard, useMe } from "@/lib/queries";
import type { DashboardItem } from "@/lib/types";
import { cn, compactNumber, greeting, relativeTime } from "@/lib/utils";

import { PageFrame } from "./app-shell";
import { OUTCOME_LABEL, STATUS_LABEL, watchTone } from "./outcome";
import { WatchRowMenu } from "./watch-menu";

type Filter = "all" | "active" | "triggered" | "error" | "subscribed";
type Sort = "updated" | "next" | "alerts" | "name";

function isTriggered(i: DashboardItem) {
  return i.alerts_24h > 0 || i.last_run?.outcome === "matched";
}
function isError(i: DashboardItem) {
  return i.watch.status === "error" || i.last_run?.outcome === "error" || i.last_run?.outcome === "blocked";
}

const noopSubscribe = () => () => {};

function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function Dashboard() {
  const me = useMe();
  const dash = useDashboard();
  const router = useRouter();
  const sp = useSearchParams();
  const q = (sp.get("q") || "").toLowerCase();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("updated");
  const now = useNow();
  const hello = useSyncExternalStore(noopSubscribe, () => greeting(), () => "Hello");

  const items = useMemo(() => dash.data?.items ?? [], [dash.data]);
  const counts = useMemo(
    () => ({
      all: items.length,
      active: items.filter((i) => i.watch.status === "active").length,
      triggered: items.filter(isTriggered).length,
      error: items.filter(isError).length,
      subscribed: items.filter((i) => !i.watch.is_owner).length,
    }),
    [items],
  );
  const shown = useMemo(() => {
    let list = items.filter((i) => {
      if (filter === "active") return i.watch.status === "active";
      if (filter === "triggered") return isTriggered(i);
      if (filter === "error") return isError(i);
      if (filter === "subscribed") return !i.watch.is_owner;
      return true;
    });
    if (q) list = list.filter((i) => `${i.watch.title} ${i.watch.description ?? ""} ${i.watch.query_text}`.toLowerCase().includes(q));
    const t = (s: string | null | undefined) => (s ? new Date(s).getTime() : Infinity);
    list = [...list].sort((a, b) => {
      if (sort === "next") return t(a.schedule.next_run_at) - t(b.schedule.next_run_at);
      if (sort === "alerts") return b.watch.alert_count - a.watch.alert_count;
      if (sort === "name") return a.watch.title.localeCompare(b.watch.title);
      return new Date(b.watch.updated_at).getTime() - new Date(a.watch.updated_at).getTime();
    });
    return list;
  }, [items, filter, sort, q]);

  // aggregate strips for the stat tiles
  const strip = (key: "runs" | "alerts") =>
    Array.from({ length: 14 }, (_, k) => items.reduce((s, i) => s + (i.activity[k]?.[key] ?? 0), 0));

  const name = me.data?.display_name?.split(" ")[0] || me.data?.handle || "";
  const t = dash.data?.totals;

  return (
    <PageFrame>
      <div className="flex items-start justify-between gap-6">
        <div>
          <h1 className="font-display text-[clamp(2.4rem,5vw,4.2rem)] leading-[0.98] text-ink">
            {hello}
            {name ? (
              <>
                , <em className="accent">{name}.</em>
              </>
            ) : (
              "."
            )}
          </h1>
          <p className="mt-3 text-[16px] text-ink-2">
            {q ? (
              <>
                Showing watches matching “{sp.get("q")}”.{" "}
                <button className="underline underline-offset-4" onClick={() => router.replace("/dashboard")}>
                  Clear
                </button>
              </>
            ) : (
              "Here's what's happening with your watches."
            )}
          </p>
        </div>
        <div className="hidden items-start gap-10 xl:flex">
          <Crosshair className="mt-2" size={40} />
          <Kicker lines={["Same web.", "More signals.", "A more", "informed you."]} />
        </div>
      </div>

      {/* stat tiles */}
      <div className="mt-8 grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        {[
          { k: "01", label: "Active watches", icon: Binoculars, value: t?.active_watches, bars: strip("runs") },
          { k: "02", label: "Checks today", icon: Database, value: t?.checks_today, bars: strip("runs") },
          { k: "03", label: "Alerts this week", icon: Bell, value: t?.alerts_7d, bars: strip("alerts"), tone: "amber" as const },
          { k: "04", label: "AI calls saved", icon: Zap, value: t?.ai_skipped_7d, bars: strip("runs"), hint: "Checks decided without AI in the last 7 days" },
        ].map((s, k) => (
          <motion.div
            key={s.k}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: k * 0.05 }}
            className="ticked border border-line bg-elevated/60 p-4 sm:p-5"
            title={s.hint}
          >
            <div className="label-mono flex gap-3 text-[10px] text-ink-2">
              <span className="text-ink-3">[{s.k}]</span>
              {s.label}
            </div>
            <div className="mt-3 flex items-end justify-between gap-3">
              <div className="flex items-center gap-3">
                <s.icon className="h-6 w-6 text-ink sm:h-7 sm:w-7" strokeWidth={1.3} aria-hidden />
                {dash.isPending ? <Skeleton className="h-9 w-14" /> : <span className="font-display text-[34px] leading-none text-ink sm:text-[40px]">{compactNumber(s.value ?? 0)}</span>}
              </div>
              <Sparkbars values={s.bars} tone={s.tone || "ink"} className="hidden sm:block" height={26} label={`${s.label} over the last 7 days`} />
            </div>
          </motion.div>
        ))}
      </div>

      {dash.isError ? (
        <ErrorState className="mt-10" error={dash.error} onRetry={() => dash.refetch()} />
      ) : !dash.isPending && items.length === 0 ? (
        <FirstWatch />
      ) : (
        <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)} className="mt-10">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <TabsList className="lg:border-b-0">
              <TabsTrigger value="all" count={counts.all}>All watches</TabsTrigger>
              <TabsTrigger value="active" count={counts.active}>Active</TabsTrigger>
              <TabsTrigger value="triggered" count={counts.triggered}>Triggered</TabsTrigger>
              <TabsTrigger value="error" count={counts.error}>Needs attention</TabsTrigger>
              {counts.subscribed > 0 && <TabsTrigger value="subscribed" count={counts.subscribed}>Subscribed</TabsTrigger>}
            </TabsList>
            <div className="flex items-center gap-2 pb-2">
              <NativeSelect aria-label="Sort watches" value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="w-48">
                <option value="updated">Sort by: Last updated</option>
                <option value="next">Sort by: Next check</option>
                <option value="alerts">Sort by: Most alerts</option>
                <option value="name">Sort by: Name</option>
              </NativeSelect>
              <Button asChild mono>
                <Link href="/watches/new">
                  <Plus className="h-4 w-4" /> New watch
                </Link>
              </Button>
            </div>
          </div>

          {dash.isPending ? (
            <div className="mt-2 space-y-2">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-[68px] w-full" />
              ))}
            </div>
          ) : shown.length === 0 ? (
            <div className="mt-10 flex flex-col items-center gap-3 py-12 text-center text-ink-2">
              <Search className="h-6 w-6 text-ink-3" aria-hidden />
              <p>{q ? "No watches match your search." : "Nothing in this view right now."}</p>
              {filter !== "all" && (
                <button className="text-sm text-ink underline underline-offset-4" onClick={() => setFilter("all")}>
                  Show all watches
                </button>
              )}
            </div>
          ) : (
            <>
              {/* desktop table */}
              <div className="mt-1 hidden overflow-x-auto md:block">
                <table className="w-full min-w-[860px] border-collapse text-left">
                  <thead>
                    <tr className="label-mono border-b border-line text-[10px] text-ink-3">
                      <th scope="col" className="w-16 py-4 pl-3 font-normal">Status</th>
                      <th scope="col" className="py-4 font-normal">Watch</th>
                      <th scope="col" className="w-48 py-4 font-normal">Last checked</th>
                      <th scope="col" className="w-36 py-4 font-normal">Next check</th>
                      <th scope="col" className="w-40 py-4 font-normal">Activity · 7d</th>
                      <th scope="col" className="w-16 py-4 pr-3 text-right font-normal">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((i) => (
                      <Row key={i.watch.id} item={i} now={now} onOpen={() => router.push(`/watches/${i.watch.id}`)} />
                    ))}
                  </tbody>
                </table>
              </div>
              {/* mobile cards */}
              <ul className="mt-4 space-y-3 md:hidden">
                {shown.map((i) => (
                  <MobileCard key={i.watch.id} item={i} now={now} />
                ))}
              </ul>
            </>
          )}
        </Tabs>
      )}
    </PageFrame>
  );
}

function LastChecked({ i, now }: { i: DashboardItem; now: number }) {
  const r = i.last_run;
  if (i.schedule.running)
    return (
      <span className="flex items-center gap-1.5 text-[13px] text-amber-ink">
        <span className="h-2 w-2 animate-blink rounded-full bg-amber" /> Checking now…
      </span>
    );
  if (!r) return <span className="text-[13px] text-ink-3">Not checked yet</span>;
  const tone = i.alerts_24h > 0 ? "amber" : r.outcome === "error" || r.outcome === "blocked" ? "err" : "ok";
  const label =
    i.alerts_24h > 0 ? `${i.alerts_24h} new update${i.alerts_24h > 1 ? "s" : ""}` : r.outcome ? OUTCOME_LABEL[r.outcome] : "In progress";
  return (
    <span className="block">
      <span className="block text-[15px] text-ink">{relativeTime(r.started_at, now)}</span>
      <span className={cn("mt-0.5 flex items-center gap-1.5 text-[13px]", tone === "amber" ? "text-amber-ink" : tone === "err" ? "text-err" : "text-ink-3")}>
        {tone === "ok" ? <CircleCheck className="h-3.5 w-3.5 text-ok" aria-hidden /> : <StatusDot tone={tone} className="h-2 w-2" />}
        {label}
      </span>
    </span>
  );
}

function NextCheck({ i, now }: { i: DashboardItem; now: number }) {
  if (i.watch.status !== "active" && i.watch.status !== "error") return <span className="text-ink-3">{STATUS_LABEL[i.watch.status] || i.watch.status}</span>;
  if (!i.schedule.next_run_at) return <span className="text-ink-3">—</span>;
  const due = new Date(i.schedule.next_run_at).getTime() <= now;
  return <span className="text-ink">{due ? "Due now" : relativeTime(i.schedule.next_run_at, now)}</span>;
}

function Row({ item: i, now, onOpen }: { item: DashboardItem; now: number; onOpen: () => void }) {
  const tone = watchTone(i.watch.status, i.last_run?.outcome, i.alerts_24h);
  const vals = i.activity.map((b) => b.runs);
  const hl = i.activity.map((b) => b.alerts > 0);
  return (
    <tr className="group cursor-pointer border-b border-line transition-colors hover:bg-elevated/70" onClick={onOpen}>
      <td className="py-4 pl-4">
        <StatusDot tone={tone} pulse={i.schedule.running} label={STATUS_LABEL[i.watch.status]} className="h-3 w-3" />
      </td>
      <td className="py-4 pr-6">
        <div className="flex items-center gap-4">
          <CategoryIcon slug={i.watch.category_slug} kind={i.watch.kind} className="h-6 w-6 shrink-0 text-ink-2" />
          <div className="min-w-0">
            <Link href={`/watches/${i.watch.id}`} onClick={(e) => e.stopPropagation()} className="block truncate text-[16px] text-ink hover:underline hover:underline-offset-4">
              {i.watch.title}
            </Link>
            <span className="flex items-center gap-2 text-[13px] text-ink-3">
              <span className="truncate">{i.watch.description || i.watch.query_text}</span>
              {!i.watch.is_owner && <Badge className="h-5 px-1.5 text-[9.5px]">Subscribed</Badge>}
              {i.watch.visibility === "public" && i.watch.is_owner && <Badge className="h-5 px-1.5 text-[9.5px]">Public</Badge>}
            </span>
          </div>
        </div>
      </td>
      <td className="py-4">
        <LastChecked i={i} now={now} />
      </td>
      <td className="py-4 text-[15px]">
        <NextCheck i={i} now={now} />
      </td>
      <td className="py-4">
        <Sparkbars values={vals} highlight={hl} tone={tone === "err" ? "err" : tone === "amber" ? "amber" : "ok"} label={`${vals.reduce((a, b) => a + b, 0)} checks in 7 days`} />
      </td>
      <td className="py-4 pr-3 text-right" onClick={(e) => e.stopPropagation()}>
        <WatchRowMenu watch={i.watch} onOpen={onOpen} />
      </td>
    </tr>
  );
}

function MobileCard({ item: i, now }: { item: DashboardItem; now: number }) {
  const tone = watchTone(i.watch.status, i.last_run?.outcome, i.alerts_24h);
  return (
    <li className="ticked relative border border-line bg-elevated/70 p-4">
      <div className="flex items-start gap-3">
        <StatusDot tone={tone} className="mt-1.5 h-3 w-3" label={STATUS_LABEL[i.watch.status]} />
        <CategoryIcon slug={i.watch.category_slug} kind={i.watch.kind} className="mt-0.5 h-5 w-5 shrink-0 text-ink-2" />
        <div className="min-w-0 flex-1">
          <Link href={`/watches/${i.watch.id}`} className="block text-[16px] font-medium leading-snug text-ink after:absolute after:inset-0">
            {i.watch.title}
          </Link>
          <p className="truncate text-[13px] text-ink-3">{i.watch.description || i.watch.query_text}</p>
          <p className="mt-1.5 text-[12.5px] text-ink-2">
            {i.last_run ? relativeTime(i.last_run.started_at, now) : "Not checked yet"}
            {i.schedule.next_run_at && i.watch.status === "active" && <> · next {relativeTime(i.schedule.next_run_at, now)}</>}
          </p>
        </div>
        <Sparkbars values={i.activity.map((b) => b.runs)} highlight={i.activity.map((b) => b.alerts > 0)} tone={tone === "err" ? "err" : tone === "amber" ? "amber" : "ok"} height={20} className="mt-6" />
      </div>
    </li>
  );
}

const EXAMPLES = [
  "Tell me when SSC CGL 2026 Tier-1 result is declared",
  "New SDE-1 backend openings at Razorpay or Zerodha in Bengaluru",
  "Sony WH-1000XM5 under ₹22,000 on Amazon India",
  "NSP scholarship portal opens for 2026-27",
];

function FirstWatch() {
  const router = useRouter();
  const [text, setText] = useState("");
  const go = (q: string) => router.push(`/watches/new?q=${encodeURIComponent(q)}`);
  return (
    <section className="ticked mt-10 border border-line bg-elevated/60 p-6 sm:p-10" aria-labelledby="first-title">
      <div className="label-mono text-ink-3">[01] Your first watch</div>
      <h2 id="first-title" className="mt-4 font-display text-[clamp(2rem,4vw,3.2rem)] leading-tight text-ink">
        What should we <em className="accent">keep an eye on?</em>
      </h2>
      <form
        className="mt-6 flex flex-col gap-3 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) go(text.trim());
        }}
      >
        <label htmlFor="first-q" className="sr-only">
          Describe what to watch
        </label>
        <input
          id="first-q"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Notify me when UPSC releases the CSE 2027 notification"
          className="mono-tight h-14 flex-1 border border-line-strong bg-bg px-4 text-[14px] text-ink placeholder:text-ink-3 focus-visible:border-ink focus-visible:outline-none"
        />
        <Button type="submit" size="lg" disabled={!text.trim()}>
          Set it up <ArrowRight className="h-4 w-4" />
        </Button>
      </form>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink-3">Try:</span>
        {EXAMPLES.map((e) => (
          <button key={e} onClick={() => go(e)} className="border border-line-strong/70 px-3 py-1.5 text-left text-[13px] text-ink-2 transition-colors hover:border-ink hover:text-ink">
            {e}
          </button>
        ))}
      </div>
      <div className="mt-8 flex items-center gap-3 border-t border-line pt-6 text-[15px] text-ink-2">
        <Sparkles className="h-5 w-5 text-amber-ink" aria-hidden />
        Prefer a ready-made one?
        <Link href="/community" className="font-medium text-ink underline underline-offset-4">
          Browse community watches
        </Link>
      </div>
    </section>
  );
}
