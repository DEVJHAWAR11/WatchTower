"use client";

import { ArrowLeft, Bell, ExternalLink, Inbox } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { use, useEffect, useMemo } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/display";
import { NativeSelect } from "@/components/ui/field";
import { AlertBody, AlertCard, FeedbackButtons } from "@/components/watch/alert-card";
import { ApiError } from "@/lib/api";
import { useAlert, useAlerts, useMyWatches } from "@/lib/queries";
import { formatDateTime, hostOf } from "@/lib/utils";

import { PageFrame, PageHeader, markAlertsSeen } from "./app-shell";

export function AlertsInbox() {
  const sp = useSearchParams();
  const router = useRouter();
  const watchId = sp.get("watch") || undefined;
  const q = useAlerts(watchId);
  const watches = useMyWatches("all");
  const titles = useMemo(() => new Map((watches.data ?? []).map((w) => [w.id, w.title])), [watches.data]);
  const alerts = q.data?.pages.flatMap((p) => p.items) ?? [];
  const pending = alerts.reduce((n, a) => n + a.actions.filter((x) => !x.decision).length, 0);

  useEffect(() => {
    markAlertsSeen();
  }, []);

  return (
    <PageFrame>
      <PageHeader
        kicker="/ Alerts"
        title={
          <>
            Signals, not <em className="accent">noise.</em>
          </>
        }
        subtitle={
          pending > 0
            ? `${pending} suggested next step${pending > 1 ? "s" : ""} waiting for your approval. Rate alerts with 👍/👎 to tune your watches.`
            : "Everything your watches found, newest first. Rate alerts with 👍/👎 to tune your watches."
        }
        actions={
          <NativeSelect
            aria-label="Filter by watch"
            value={watchId || ""}
            onChange={(e) => router.replace(e.target.value ? `/alerts?watch=${e.target.value}` : "/alerts")}
            className="w-64"
          >
            <option value="">All watches</option>
            {(watches.data ?? []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.title}
              </option>
            ))}
          </NativeSelect>
        }
      />
      <div className="mt-10 max-w-4xl">
        {q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.isPending ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        ) : alerts.length === 0 ? (
          <EmptyState
            icon={<Inbox />}
            title={watchId ? "No alerts from this watch yet" : "Your inbox is quiet"}
            body="Alerts appear here the moment a watch's condition is met. Unchanged pages and irrelevant changes never reach you."
            action={
              <div className="flex flex-wrap justify-center gap-3">
                <Button asChild mono>
                  <Link href="/watches/new">Create a watch</Link>
                </Button>
                <Button asChild variant="outline" mono>
                  <Link href="/community">Subscribe to community watches</Link>
                </Button>
              </div>
            }
          />
        ) : (
          <ul className="space-y-3">
            {alerts.map((a, i) => (
              <motion.li key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }}>
                <AlertCard alert={a} watchTitle={titles.get(a.watch_id)} showWatch={!watchId} />
              </motion.li>
            ))}
          </ul>
        )}
        {q.hasNextPage && (
          <div className="mt-8 flex justify-center">
            <Button variant="outline" mono onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>
              Load older alerts
            </Button>
          </div>
        )}
      </div>
    </PageFrame>
  );
}

export function AlertDetailRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <AlertDetail id={id} />;
}

function AlertDetail({ id }: { id: string }) {
  const q = useAlert(id);
  const watches = useMyWatches("all");
  const a = q.data;
  const watchTitle = a ? watches.data?.find((w) => w.id === a.watch_id)?.title : undefined;
  return (
    <PageFrame>
      <Link href="/alerts" className="inline-flex items-center gap-2 text-[15px] text-ink-2 hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> All alerts
      </Link>
      <div className="mt-6 max-w-4xl">
        {q.isError ? (
          q.error instanceof ApiError && [403, 404, 422].includes(q.error.status) ? (
            <EmptyState icon={<Bell />} title="Alert not found" body="It may belong to a watch you no longer follow." />
          ) : (
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          )
        ) : !a ? (
          <div className="space-y-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-12 w-3/4" />
            <Skeleton className="h-48 w-full" />
          </div>
        ) : (
          <article className="ticked relative border border-line bg-elevated/70" aria-labelledby="alert-title">
            <span className="absolute inset-y-6 left-0 w-[3px] bg-amber" aria-hidden />
            <div className="flex gap-4 p-5 sm:p-7">
              <div className="min-w-0 flex-1">
                <div className="label-mono flex flex-wrap items-center gap-2 text-ink-2">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-amber text-[10px] text-on-amber">★</span>
                  Condition met
                  <span className="normal-case tracking-normal text-ink-3">· {formatDateTime(a.created_at)}</span>
                </div>
                <h1 id="alert-title" className="mt-4 font-display text-[clamp(2rem,4vw,3rem)] leading-[1.05] text-ink">
                  {a.act_result?.headline || a.title}
                </h1>
                <p className="mt-3 text-[16px] leading-relaxed text-ink-2">{a.act_result?.what_happened || a.summary}</p>
                <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-[14px]">
                  <a href={a.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-ink underline underline-offset-4">
                    Source · {hostOf(a.source_url)} <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  <Link href={`/watches/${a.watch_id}`} className="text-ink-2 underline underline-offset-4 hover:text-ink">
                    {watchTitle ? `Watch: ${watchTitle}` : "Open the watch"}
                  </Link>
                </div>
              </div>
              <FeedbackButtons alert={a} />
            </div>
            <AlertBody alert={a} />
          </article>
        )}
      </div>
    </PageFrame>
  );
}
