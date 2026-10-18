"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ExternalLink, GitCompare, History, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { DECIDED_BY_LABEL, OUTCOME_LABEL, outcomeTone } from "@/components/app/outcome";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState, ErrorState, Skeleton, StatusDot } from "@/components/ui/display";
import { NativeSelect } from "@/components/ui/field";
import { Dialog, DialogContent, Switch } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useRefinements, useVersions, useWatchRuns } from "@/lib/queries";
import type { Refinement, Run, Version, WatchSourceState, WatchState } from "@/lib/types";
import { cn, formatDateTime, formatInterval, hostOf, relativeTime } from "@/lib/utils";

// ------------------------------------------------------------------ source health
export function SourceHealth({ sources, compact }: { sources: WatchSourceState[]; compact?: boolean }) {
  const online = sources.filter((s) => s.status === "ok" || s.status === "active" || s.status === "new").length;
  return (
    <div>
      {compact && (
        <div className="flex items-center justify-between">
          <div className="label-mono text-ink-2">
            <div className="text-ink-3">[04]</div>
            Source health
          </div>
          <span className="label-mono text-ink-3">
            {online} / {sources.length} online
          </span>
        </div>
      )}
      {sources.length === 0 ? (
        <p className="mt-4 text-sm text-ink-3">Source details are visible to the watch owner.</p>
      ) : (
        <ul className={cn("ticked divide-y divide-line border border-line-strong bg-bg/60", compact ? "mt-4" : "")}>
          {sources.map((s) => {
            const ok = s.status === "ok" || s.status === "active";
            const fresh = s.status === "new";
            return (
              <li key={s.url} className="flex items-center gap-3 px-4 py-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center border border-line bg-sunken font-mono text-[11px] uppercase text-ink-2" aria-hidden>
                  {hostOf(s.url).slice(0, 2)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14.5px] text-ink">{s.label || hostOf(s.url)}</p>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="block truncate text-[12.5px] text-info underline underline-offset-2">
                    {s.url}
                  </a>
                  {!compact && (
                    <p className="mt-1 text-[12.5px] text-ink-3">
                      {s.last_fetched_at ? `Last fetched ${relativeTime(s.last_fetched_at)}` : "Not fetched yet"}
                      {s.last_status_code ? ` · HTTP ${s.last_status_code}` : ""}
                      {s.status_reason ? ` · ${s.status_reason}` : ""}
                    </p>
                  )}
                </div>
                <span className={cn("flex shrink-0 items-center gap-2 text-[13px]", ok ? "text-ink-2" : fresh ? "text-ink-3" : "text-err")}>
                  <StatusDot tone={ok ? "ok" : fresh ? "idle" : "err"} className="h-2 w-2" />
                  {ok ? "Online" : fresh ? "Pending" : s.status === "blocked" ? "Blocked" : s.status === "dead" ? "Gone" : "Error"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ check history
export function RunHistory({ watchId, onSelect }: { watchId: string; onSelect: (r: Run) => void }) {
  const [outcome, setOutcome] = useState("");
  const q = useWatchRuns(watchId, outcome || undefined, 30);
  const runs = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[15px] text-ink-2">Every check, newest first. Select one to see each step the agent took.</p>
        <NativeSelect aria-label="Filter by outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} className="w-52">
          <option value="">All outcomes</option>
          {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </NativeSelect>
      </div>
      {q.isError ? (
        <ErrorState className="mt-6" error={q.error} onRetry={() => q.refetch()} />
      ) : q.isPending ? (
        <div className="mt-6 space-y-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : runs.length === 0 ? (
        <EmptyState className="mt-6" icon={<History />} title="No checks yet" body="The first check runs shortly after a watch is created." />
      ) : (
        <ul className="mt-6 divide-y divide-line border-y border-line">
          {runs.map((r) => (
            <li key={r.id}>
              <button onClick={() => onSelect(r)} className="flex w-full flex-col gap-1 px-2 py-3.5 text-left transition-colors hover:bg-elevated sm:flex-row sm:items-center sm:gap-6">
                <span className="flex w-56 shrink-0 items-center gap-3">
                  <StatusDot tone={outcomeTone(r.outcome)} />
                  <span className="text-[15px] text-ink">{r.outcome ? OUTCOME_LABEL[r.outcome] : "Running…"}</span>
                </span>
                <span className="min-w-0 flex-1 truncate text-[13.5px] text-ink-2">{r.reason || (r.decided_by ? DECIDED_BY_LABEL[r.decided_by] : "")}</span>
                <span className="flex shrink-0 items-center gap-3 text-[13px] text-ink-3">
                  {r.llm_called ? <Badge>AI</Badge> : <Badge tone="ok">No AI</Badge>}
                  <time dateTime={r.started_at} title={formatDateTime(r.started_at)}>
                    {relativeTime(r.started_at)}
                  </time>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {q.hasNextPage && (
        <div className="mt-6 flex justify-center">
          <Button variant="outline" mono onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>
            Load older checks
          </Button>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ refinement banner
export function RefinementBanner({ watchId, proposal }: { watchId: string; proposal: Refinement }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<"accept" | "reject" | null>(null);
  const decide = async (d: "accept" | "reject") => {
    setBusy(d);
    try {
      await api(`watches/${watchId}/refinements/${proposal.id}/${d}`, { method: "POST" });
      toast.success(d === "accept" ? "Improvement applied as a new version" : "Suggestion dismissed");
      qc.invalidateQueries({ queryKey: ["watch", watchId] });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const bt = proposal.backtest as { precision_before?: number; precision_after?: number; recall_after?: number; samples?: number };
  return (
    <Card className="border-amber/60 bg-amber-soft/40 p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <Sparkles className="h-5 w-5 shrink-0 text-amber-ink" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">Suggested improvement from your feedback</p>
          <p className="mt-1 text-[14.5px] text-ink-2">{proposal.rationale}</p>
          {proposal.changes.length > 0 && (
            <ul className="mt-2 space-y-1">
              {proposal.changes.slice(0, 4).map((c, i) => (
                <li key={i} className="mono-tight text-[12px] text-ink-2">
                  › {typeof c === "string" ? c : JSON.stringify(c)}
                </li>
              ))}
            </ul>
          )}
          {bt && typeof bt.precision_after === "number" && (
            <p className="mt-2 text-[13px] text-ink-3">
              Backtest on {bt.samples ?? "past"} alerts: precision {Math.round((bt.precision_before ?? 0) * 100)}% → {Math.round(bt.precision_after * 100)}%
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" onClick={() => decide("accept")} loading={busy === "accept"}>
            <Check className="h-4 w-4" /> Apply
          </Button>
          <Button size="sm" variant="outline" onClick={() => decide("reject")} loading={busy === "reject"}>
            <X className="h-4 w-4" /> Dismiss
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ versions & tuning
export function Tuning({ state }: { state: WatchState }) {
  const id = state.watch.id;
  const qc = useQueryClient();
  const versions = useVersions(id, true);
  const refinements = useRefinements(id, true);
  const [diff, setDiff] = useState<{ a: number; b: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const current = state.current_version?.version;

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    try {
      await fn();
      toast.success(ok);
      qc.invalidateQueries({ queryKey: ["watch", id] });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-10">
      <Card className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-medium text-ink">Self-tuning</p>
          <p className="mt-1 max-w-xl text-[14.5px] text-ink-2">
            Your 👍/👎 on alerts teach the agent. With auto-tune on, improvements that pass a backtest are applied automatically; otherwise they wait here for you.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <AutoTuneSwitch watchId={id} initial={state.watch.auto_tune} />
          <Button variant="outline" mono onClick={() => run("refine", () => api(`watches/${id}/refine`, { method: "POST" }), "Looking for improvements. Suggestions appear here.")} loading={busy === "refine"}>
            <Sparkles className="h-4 w-4" /> Suggest now
          </Button>
        </div>
      </Card>

      <section aria-labelledby="sugg-title">
        <h3 id="sugg-title" className="label-mono text-ink-3">Suggestions</h3>
        {refinements.isPending ? (
          <Skeleton className="mt-3 h-20 w-full" />
        ) : (refinements.data ?? []).length === 0 ? (
          <p className="mt-3 text-[14.5px] text-ink-2">No suggestions yet. They appear after you give feedback on a few alerts.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {(refinements.data ?? []).map((r) =>
              r.status === "pending" ? (
                <li key={r.id}>
                  <RefinementBanner watchId={id} proposal={r} />
                </li>
              ) : (
                <li key={r.id} className="flex items-center justify-between gap-3 border-b border-line py-2 text-[14px]">
                  <span className="min-w-0 truncate text-ink-2">{r.rationale}</span>
                  <Badge tone={r.status === "applied" ? "ok" : "neutral"}>{r.status}</Badge>
                </li>
              ),
            )}
          </ul>
        )}
      </section>

      <section aria-labelledby="ver-title">
        <h3 id="ver-title" className="label-mono text-ink-3">Version history</h3>
        {versions.isError ? (
          <ErrorState className="mt-3" error={versions.error} onRetry={() => versions.refetch()} />
        ) : versions.isPending ? (
          <Skeleton className="mt-3 h-40 w-full" />
        ) : (
          <ol className="mt-3 divide-y divide-line border-y border-line">
            {(versions.data ?? []).map((v: Version, i, all) => (
              <li key={v.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
                <span className="w-14 shrink-0 font-display text-2xl text-ink">v{v.version}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-[14.5px] text-ink">{v.changelog || "Initial version"}</p>
                  <p className="text-[12.5px] text-ink-3">
                    {formatDateTime(v.created_at)} · by {v.created_by} · {formatInterval(v.spec.interval_seconds)}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  {v.version === current ? (
                    <Badge tone="ok">Current</Badge>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => run(`rb${v.version}`, () => api(`watches/${id}/versions/${v.version}/rollback`, { method: "POST" }), `Rolled back to v${v.version}`)} loading={busy === `rb${v.version}`}>
                      <RotateCcw className="h-3.5 w-3.5" /> Restore
                    </Button>
                  )}
                  {i < all.length - 1 && (
                    <Button size="sm" variant="ghost" onClick={() => setDiff({ a: all[i + 1].version, b: v.version })}>
                      <GitCompare className="h-3.5 w-3.5" /> Changes
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
      <DiffDialog watchId={id} pair={diff} onClose={() => setDiff(null)} />
    </div>
  );
}

function AutoTuneSwitch({ watchId, initial }: { watchId: string; initial: boolean }) {
  const [on, setOn] = useState(initial);
  const toggle = async (v: boolean) => {
    setOn(v);
    try {
      await api(`watches/${watchId}`, { method: "PATCH", body: { auto_tune: v } });
      toast.success(v ? "Auto-tune on" : "Auto-tune off");
    } catch (e) {
      setOn(!v);
      toast.error(errorMessage(e));
    }
  };
  return (
    <label className="flex items-center gap-2 text-[14px] text-ink-2">
      <Switch checked={on} onCheckedChange={toggle} label="Auto-tune" /> Auto-tune
    </label>
  );
}

function DiffDialog({ watchId, pair, onClose }: { watchId: string; pair: { a: number; b: number } | null; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["watch", watchId, "diff", pair?.a, pair?.b],
    queryFn: () =>
      api<{ changes: { field: string; from: unknown; to: unknown }[]; changelog: string | null }>(`watches/${watchId}/versions/diff`, {
        query: { a: pair!.a, b: pair!.b },
      }),
    enabled: Boolean(pair),
  });
  const data = q.data;
  const err = q.error;
  const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v, null, 1));
  return (
    <Dialog open={Boolean(pair)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={pair ? `v${pair.a} → v${pair.b}` : "Changes"} description={data?.changelog || undefined}>
        {err ? (
          <ErrorState error={err} />
        ) : !data ? (
          <Skeleton className="h-32 w-full" />
        ) : data.changes.length === 0 ? (
          <p className="text-ink-2">No differences.</p>
        ) : (
          <ul className="space-y-4">
            {data.changes.map((c) => (
              <li key={c.field}>
                <p className="label-mono text-ink-3">{c.field}</p>
                <div className="mono-tight mt-1.5 grid gap-1 text-[12px]">
                  <pre className="whitespace-pre-wrap break-words bg-err-soft/60 px-3 py-2 text-err">− {show(c.from)}</pre>
                  <pre className="whitespace-pre-wrap break-words bg-ok-soft/60 px-3 py-2 text-ok">+ {show(c.to)}</pre>
                </div>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function SourcesPanel({ state }: { state: WatchState }) {
  const spec = state.current_version?.spec;
  return (
    <div className="space-y-6">
      <SourceHealth sources={state.sources} />
      {spec && (
        <Card className="p-5 text-[14.5px] text-ink-2">
          <p>
            Checked <strong className="font-medium text-ink">{formatInterval(spec.interval_seconds).toLowerCase()}</strong>.{" "}
            {spec.sources.some((s) => s.fetch_mode === "render") ? "Some pages are rendered in a browser because they need JavaScript." : "Pages are fetched politely and conditionally, so unchanged pages cost almost nothing."}
          </p>
          {spec.keywords.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {spec.keywords.map((k) => (
                <Badge key={k}>{k}</Badge>
              ))}
            </div>
          )}
          <a href="#settings" className="mt-4 inline-flex items-center gap-1 text-ink underline underline-offset-4" onClick={(e) => { e.preventDefault(); document.getElementById("tab-settings")?.click(); }}>
            Edit sources in settings <ArrowRight className="h-3.5 w-3.5" />
          </a>
        </Card>
      )}
      <p className="flex items-center gap-2 text-[13px] text-ink-3">
        <ExternalLink className="h-3.5 w-3.5" /> We respect robots.txt and rate-limit every site, shared across all users.
      </p>
    </div>
  );
}
