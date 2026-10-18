"use client";

import { Check, CircleDashed, X } from "lucide-react";
import Link from "next/link";

import { DECIDED_BY_LABEL, NODE_LABEL, OUTCOME_LABEL, outcomeTone } from "@/components/app/outcome";
import { Badge, ErrorState, Skeleton, StatusDot } from "@/components/ui/display";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { useRunDetail } from "@/lib/queries";
import { cn, formatDateTime } from "@/lib/utils";

/** Full trace of one check: every agent step with its note and timing. */
export function RunDialog({ watchId, runId, onClose }: { watchId: string; runId: string | null; onClose: () => void }) {
  const q = useRunDetail(watchId, runId);
  const r = q.data;
  return (
    <Dialog open={Boolean(runId)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={r ? (r.outcome ? OUTCOME_LABEL[r.outcome] : "Check in progress") : "Check details"} description={r ? `${formatDateTime(r.started_at)} · ${r.trigger === "manual" ? "manual check" : "scheduled check"}` : undefined}>
        {q.isPending ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : r ? (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              <Badge tone={outcomeTone(r.outcome) === "amber" ? "amber" : outcomeTone(r.outcome) === "err" ? "err" : "neutral"}>
                <StatusDot tone={outcomeTone(r.outcome)} className="h-2 w-2" /> {r.outcome ? OUTCOME_LABEL[r.outcome] : r.status}
              </Badge>
              {r.decided_by && <Badge>{DECIDED_BY_LABEL[r.decided_by] || r.decided_by}</Badge>}
              {r.duration_ms !== null && <Badge>{(r.duration_ms / 1000).toFixed(1)}s</Badge>}
              {r.llm_called && <Badge>{r.llm_tokens.toLocaleString("en-IN")} AI tokens</Badge>}
              {r.confidence !== null && <Badge>Confidence {Math.round(r.confidence * 100)}%</Badge>}
            </div>
            {r.reason && <p className="text-[15px] text-ink-2">{r.reason}</p>}
            {r.diff_summary && (
              <div>
                <h3 className="label-mono text-ink-3">What changed</h3>
                <pre className="mono-tight mt-2 max-h-48 overflow-auto whitespace-pre-wrap border border-line bg-bg/60 p-3 text-[12px] text-ink-2">{r.diff_summary}</pre>
              </div>
            )}
            <div>
              <h3 className="label-mono text-ink-3">Steps</h3>
              <ol className="mt-3 space-y-0">
                {r.steps.length === 0 && <li className="text-sm text-ink-3">No steps were recorded for this check.</li>}
                {r.steps.map((s, k) => {
                  const bad = s.status === "error" || s.status === "failed";
                  const skipped = s.status === "skipped";
                  return (
                    <li key={k} className="relative flex gap-4 pb-4 last:pb-0">
                      {k < r.steps.length - 1 && <span className="absolute left-[11px] top-6 h-full w-px bg-line" aria-hidden />}
                      <span className={cn("relative z-10 grid h-6 w-6 shrink-0 place-items-center rounded-full border bg-elevated", bad ? "border-err text-err" : skipped ? "border-line-strong text-ink-3" : "border-ok text-ok")}>
                        {bad ? <X className="h-3.5 w-3.5" /> : skipped ? <CircleDashed className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="font-medium text-ink">{NODE_LABEL[s.node] || s.node}</span>
                          {s.ms !== undefined && s.ms !== null && <span className="mono-tight text-[11px] text-ink-3">{s.ms < 1000 ? `${s.ms}ms` : `${(s.ms / 1000).toFixed(1)}s`}</span>}
                        </div>
                        {s.note && <p className="mt-0.5 break-words text-[13.5px] text-ink-2">{s.note}</p>}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
            {r.error_code && <p className="text-[13px] text-err">Error code: {r.error_code}</p>}
            {r.alert_id && (
              <Link href={`/alerts/${r.alert_id}`} className="inline-flex text-[15px] font-medium text-ink underline underline-offset-4">
                Open the alert from this check →
              </Link>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
