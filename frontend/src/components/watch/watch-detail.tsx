"use client";

import { ArrowLeft, Bell, Calendar, ChevronDown, Database, Pause, Pencil, Play, RefreshCw, Users, Zap } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { CategoryArt, CategoryIcon, categoryOf } from "@/components/art/category";
import { PageFrame } from "@/components/app/app-shell";
import { STATUS_LABEL, watchTone } from "@/components/app/outcome";
import { WatchRowMenu, useWatchMutations } from "@/components/app/watch-menu";
import { SubscribeButton } from "@/components/community/watch-card";
import { Button } from "@/components/ui/button";
import { Badge, EmptyState, ErrorState, Kicker, Skeleton, StatusDot } from "@/components/ui/display";
import { NativeSelect } from "@/components/ui/field";
import { Menu, MenuContent, MenuItem, MenuTrigger, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useWatchAlerts, useWatchRuns, useWatchState } from "@/lib/queries";
import type { Run } from "@/lib/types";
import { compactNumber, formatDate, relativeTime } from "@/lib/utils";

import { AlertCard } from "./alert-card";
import { LiveLog, useLiveLog } from "./live-log";
import { RefinementBanner, RunHistory, SourceHealth, SourcesPanel, Tuning } from "./panels";
import { RunDialog } from "./run-dialog";
import { WatchSettings } from "./settings-panel";
import { CheckTimeline } from "./timeline";

export function WatchDetail({ id }: { id: string }) {
  const q = useWatchState(id);
  const router = useRouter();
  const sp = useSearchParams();
  const tab = sp.get("tab") || "overview";
  const setTab = (t: string) => router.replace(`?tab=${t}`, { scroll: false });
  const [runId, setRunId] = useState<string | null>(null);
  const runs = useWatchRuns(id, undefined, 100);
  const alerts = useWatchAlerts(id);
  const log = useLiveLog(id, q.data?.last_run);

  if (q.isError) {
    const notFound = q.error instanceof ApiError && (q.error.status === 404 || q.error.status === 403 || q.error.status === 422);
    return (
      <PageFrame>
        {notFound ? (
          <EmptyState title="Watch not found" body="It may have been archived, or it's private to someone else." action={<Button asChild><Link href="/dashboard">Back to my watches</Link></Button>} />
        ) : (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        )}
      </PageFrame>
    );
  }
  if (q.isPending) return <DetailSkeleton />;

  const s = q.data;
  const w = s.watch;
  const cat = categoryOf(w.category_slug, w.kind);
  const allRuns = runs.data?.pages.flatMap((p) => p.items) ?? [];
  const allAlerts = alerts.data?.pages.flatMap((p) => p.items) ?? [];
  const owner = w.is_owner;
  const running = log.running || s.schedule.running;

  return (
    <PageFrame>
      <div className="grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0">
          <Link href={owner || w.is_subscribed ? "/dashboard" : "/community"} className="inline-flex items-center gap-2 text-[15px] text-ink-2 hover:text-ink">
            <ArrowLeft className="h-4 w-4" /> {owner || w.is_subscribed ? "Back to my watches" : "Back to community"}
          </Link>

          <Header state={s} running={running} />

          {owner && s.pending_refinement && (
            <div className="mt-6">
              <RefinementBanner watchId={id} proposal={s.pending_refinement} />
            </div>
          )}
          {w.status === "error" && w.status_reason && (
            <div className="mt-6 border border-err/30 bg-err-soft/60 p-4 text-[14.5px] text-ink" role="status">
              <strong className="font-medium">Needs attention:</strong> {w.status_reason}
            </div>
          )}

          <Tabs value={tab} onValueChange={setTab} className="mt-8">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="alerts" count={w.alert_count}>Alerts</TabsTrigger>
              <TabsTrigger value="history">Checks</TabsTrigger>
              {s.sources.length > 0 && <TabsTrigger value="sources" count={s.sources.length}>Sources</TabsTrigger>}
              {owner && <TabsTrigger value="tuning">Tuning</TabsTrigger>}
              {(owner || w.is_subscribed) && (
                <TabsTrigger value="settings">
                  <span id="tab-settings">Settings</span>
                </TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="overview" className="pt-8 focus-visible:outline-none">
              <Stats state={s} />
              <div className="mt-10">
                <CheckTimeline runs={allRuns} loading={runs.isPending} onSelect={(r: Run) => setRunId(r.id)} />
              </div>
              {/* the live log moves under the timeline on smaller screens */}
              <div className="mt-10 xl:hidden">
                <LiveLog lines={log.lines} running={running} status={log.status} />
              </div>
              <AlertHistory alerts={allAlerts} loading={alerts.isPending} error={alerts.error} onRetry={() => alerts.refetch()} hasMore={alerts.hasNextPage} onMore={() => alerts.fetchNextPage()} loadingMore={alerts.isFetchingNextPage} />
            </TabsContent>

            <TabsContent value="alerts" className="pt-8 focus-visible:outline-none">
              <AlertHistory alerts={allAlerts} loading={alerts.isPending} error={alerts.error} onRetry={() => alerts.refetch()} hasMore={alerts.hasNextPage} onMore={() => alerts.fetchNextPage()} loadingMore={alerts.isFetchingNextPage} full />
            </TabsContent>
            <TabsContent value="history" className="pt-8 focus-visible:outline-none">
              <RunHistory watchId={id} onSelect={(r) => setRunId(r.id)} />
            </TabsContent>
            <TabsContent value="sources" className="pt-8 focus-visible:outline-none">
              <SourcesPanel state={s} />
            </TabsContent>
            {owner && (
              <TabsContent value="tuning" className="pt-8 focus-visible:outline-none">
                <Tuning state={s} />
              </TabsContent>
            )}
            <TabsContent value="settings" className="pt-8 focus-visible:outline-none">
              <WatchSettings key={s.current_version?.id || w.updated_at} state={s} />
            </TabsContent>
          </Tabs>
        </div>

        {/* right rail */}
        <aside className="hidden space-y-10 xl:block" aria-label="Live status">
          <div className="sticky top-[112px] space-y-10">
            <div className="flex items-start justify-end gap-4">
              <Kicker className="text-right" lines={["Global monitoring", "Real time signals", "Always on"]} />
            </div>
            <LiveLog lines={log.lines} running={running} status={log.status} />
            {s.sources.length > 0 && <SourceHealth sources={s.sources} compact />}
          </div>
        </aside>
      </div>
      <RunDialog watchId={id} runId={runId} onClose={() => setRunId(null)} />
      <span className="sr-only">{cat.label}</span>
    </PageFrame>
  );
}

function Header({ state: s, running }: { state: NonNullable<ReturnType<typeof useWatchState>["data"]>; running: boolean }) {
  const w = s.watch;
  const router = useRouter();
  const m = useWatchMutations(w);
  const [busy, setBusy] = useState<string | null>(null);
  const tone = watchTone(w.status, s.last_run?.outcome, 0);
  const canRun = w.is_owner && (w.status === "active" || w.status === "error");
  const paused = w.status === "paused" || w.status === "completed" || w.status === "expired";
  const go = async (k: string, fn: () => Promise<boolean>) => {
    setBusy(k);
    await fn();
    setBusy(null);
  };

  return (
    <div className="mt-6 flex flex-col-reverse gap-5 2xl:flex-row 2xl:items-start">
      <div className="min-w-0 flex-1">
        <div className="label-mono flex items-center gap-2 text-ink-2">
          <CategoryIcon slug={w.category_slug} kind={w.kind} className="h-5 w-5 text-amber-ink" />
          {categoryOf(w.category_slug, w.kind).label}
          {w.visibility !== "private" && <Badge className="ml-2">{w.visibility}</Badge>}
          {!w.is_owner && w.owner && <span className="normal-case tracking-normal text-ink-3">· by {w.owner.is_community ? "Watchtower Community" : `@${w.owner.handle || "member"}`}</span>}
        </div>
        <motion.h1 initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-3 font-display text-[clamp(2.2rem,4.4vw,3.8rem)] leading-[1.02] text-ink">
          {w.title}
        </motion.h1>
        {(w.description || w.query_text) && <p className="mt-3 max-w-2xl text-[16.5px] leading-relaxed text-ink-2">{w.description || w.query_text}</p>}
        <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3 text-[14.5px] text-ink-2">
          {w.is_owner ? (
            <Menu>
              <MenuTrigger className="flex items-center gap-2 text-ink hover:underline hover:underline-offset-4" aria-label="Change status">
                <StatusDot tone={tone} pulse={running} className="h-3 w-3" />
                {running ? "Checking now" : STATUS_LABEL[w.status] || w.status}
                <ChevronDown className="h-4 w-4 text-ink-3" />
              </MenuTrigger>
              <MenuContent align="start">
                {paused ? (
                  <MenuItem icon={<Play />} onSelect={() => m.resume()}>
                    Resume checking
                  </MenuItem>
                ) : (
                  <MenuItem icon={<Pause />} onSelect={() => m.pause()} disabled={w.status === "archived"}>
                    Pause checking
                  </MenuItem>
                )}
                <MenuItem icon={<RefreshCw />} onSelect={() => m.checkNow()} disabled={!canRun}>
                  Check now
                </MenuItem>
              </MenuContent>
            </Menu>
          ) : (
            <span className="flex items-center gap-2 text-ink">
              <StatusDot tone={tone} pulse={running} className="h-3 w-3" /> {running ? "Checking now" : STATUS_LABEL[w.status] || w.status}
            </span>
          )}
          <span className="h-5 w-px bg-line" aria-hidden />
          <span className="flex items-center gap-2">
            <Users className="h-4 w-4 text-ink-3" aria-hidden /> {compactNumber(w.subscriber_count)} subscriber{w.subscriber_count === 1 ? "" : "s"}
          </span>
          <span className="h-5 w-px bg-line" aria-hidden />
          <span className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-ink-3" aria-hidden /> Created {formatDate(w.created_at)}
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-start gap-4 2xl:order-last">
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
          {w.is_owner ? (
            <>
              <Button variant="outline" mono className="h-9 px-3 sm:h-10 sm:px-4" onClick={() => router.replace("?tab=settings", { scroll: false })}>
                <Pencil className="h-4 w-4" /> Edit
              </Button>
              {paused ? (
                <Button variant="outline" mono className="h-9 px-3 sm:h-10 sm:px-4" onClick={() => go("resume", m.resume)} loading={busy === "resume"}>
                  <Play className="h-4 w-4" /> Resume
                </Button>
              ) : (
                <Button variant="outline" mono className="h-9 px-3 sm:h-10 sm:px-4" onClick={() => go("pause", m.pause)} loading={busy === "pause"} disabled={w.status === "archived"}>
                  <Pause className="h-4 w-4" /> Pause
                </Button>
              )}
              <Button mono className="h-9 px-3 sm:h-10 sm:px-4" onClick={() => go("run", m.checkNow)} loading={busy === "run"} disabled={!canRun || running}>
                <RefreshCw className="h-4 w-4" /> Check now
              </Button>
            </>
          ) : (
            <SubscribeButton watch={w} subscribed={w.is_subscribed} size="md" />
          )}
          <WatchRowMenu watch={w} onOpen={() => router.refresh()} />
        </div>
        <CategoryArt slug={w.category_slug} kind={w.kind} seed={w.id} className="hidden h-32 w-36 border border-line grayscale 2xl:block" />
      </div>
    </div>
  );
}

function Stats({ state: s }: { state: NonNullable<ReturnType<typeof useWatchState>["data"]> }) {
  const st = s.stats;
  const items = [
    { icon: Database, label: "Checks · 7d", value: st.runs_7d },
    { icon: Zap, label: "AI calls · 7d", value: st.llm_calls_7d, hint: st.ai_skip_ratio_7d !== null ? `${Math.round((st.ai_skip_ratio_7d || 0) * 100)}% decided without AI` : undefined },
    { icon: Bell, label: "Alerts · 7d", value: st.alerts_7d },
    { icon: RefreshCw, label: "Next check", value: null, text: s.schedule.next_run_at ? relativeTime(s.schedule.next_run_at) : s.watch.status === "active" ? "Soon" : STATUS_LABEL[s.watch.status] },
  ];
  return (
    <div className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
      {items.map((x) => (
        <div key={x.label} className="bg-bg p-4">
          <div className="label-mono flex items-center gap-2 text-[10px] text-ink-3">
            <x.icon className="h-3.5 w-3.5" aria-hidden /> {x.label}
          </div>
          <div className="mt-2 font-display text-[28px] leading-none text-ink">{x.text ?? compactNumber(x.value ?? 0)}</div>
          {x.hint && <div className="mt-1.5 text-[12px] text-ok">{x.hint}</div>}
        </div>
      ))}
    </div>
  );
}

function AlertHistory({
  alerts,
  loading,
  error,
  onRetry,
  hasMore,
  onMore,
  loadingMore,
  full,
}: {
  alerts: NonNullable<ReturnType<typeof useWatchAlerts>["data"]>["pages"][number]["items"];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  hasMore: boolean;
  onMore: () => void;
  loadingMore: boolean;
  full?: boolean;
}) {
  const [filter, setFilter] = useState("all");
  const shown = useMemo(
    () =>
      alerts.filter((a) =>
        filter === "relevant" ? a.my_feedback === true : filter === "irrelevant" ? a.my_feedback === false : filter === "unrated" ? a.my_feedback === null : true,
      ),
    [alerts, filter],
  );
  return (
    <section className={full ? "" : "mt-12"} aria-labelledby="alert-history">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {!full ? (
          <div className="label-mono text-ink-2">
            <div className="text-ink-3">[03]</div>
            <span id="alert-history">Alert history</span>
          </div>
        ) : (
          <h2 id="alert-history" className="sr-only">
            Alerts
          </h2>
        )}
        <NativeSelect aria-label="Filter alerts" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-44">
          <option value="all">All alerts</option>
          <option value="unrated">Not rated yet</option>
          <option value="relevant">Relevant</option>
          <option value="irrelevant">Not relevant</option>
        </NativeSelect>
      </div>
      {error ? (
        <ErrorState className="mt-4" error={error} onRetry={onRetry} />
      ) : loading ? (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <EmptyState
          className="mt-4"
          icon={<Bell />}
          title={alerts.length ? "Nothing in this filter" : "No alerts yet"}
          body={alerts.length ? "Try another filter." : "When the condition is met you'll get one complete alert here and on your channels. Until then, the agent checks quietly."}
        />
      ) : (
        <ul className="mt-4 space-y-3">
          {(full ? shown : shown.slice(0, 5)).map((a, i) => (
            <motion.li key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.04, 0.3) }}>
              <AlertCard alert={a} />
            </motion.li>
          ))}
        </ul>
      )}
      {full && hasMore && (
        <div className="mt-6 flex justify-center">
          <Button variant="outline" mono onClick={onMore} loading={loadingMore}>
            Load older alerts
          </Button>
        </div>
      )}
    </section>
  );
}

function DetailSkeleton() {
  return (
    <PageFrame>
      <div className="grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-14 w-3/4" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="mt-8 h-10 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
        <div className="hidden space-y-4 xl:block">
          <Skeleton className="h-[400px] w-full" />
        </div>
      </div>
    </PageFrame>
  );
}
