"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NODE_LABEL, OUTCOME_LABEL } from "@/components/app/outcome";
import type { LiveEvent, StreamStatus } from "@/lib/stream";
import { useWatchStream } from "@/lib/stream";
import type { RunDetail, RunOutcome } from "@/lib/types";
import { cn, formatClock, relativeTime } from "@/lib/utils";

export interface LogLine {
  key: string;
  at: string;
  text: string;
  tone?: "ok" | "amber" | "err" | "dim";
  runId?: string;
}

function lineFromEvent(e: LiveEvent): LogLine | null {
  const d = e.data as Record<string, unknown>;
  const base = { key: e.id + e.type, at: e.at, runId: (d.run_id as string) || undefined };
  switch (e.type) {
    case "run.started":
      return { ...base, text: d.trigger === "manual" ? "Starting manual check…" : "Starting scheduled check…" };
    case "run.step": {
      const node = String(d.node || "");
      const note = d.note ? String(d.note) : "";
      const st = String(d.status || "");
      const label = NODE_LABEL[node] || node;
      const ms = typeof d.ms === "number" && d.ms > 0 ? ` (${d.ms < 1000 ? `${d.ms}ms` : `${(d.ms / 1000).toFixed(1)}s`})` : "";
      const tone = st === "error" || st === "failed" ? "err" : node === "fire" ? "amber" : st === "skipped" ? "dim" : undefined;
      return { ...base, text: `${note || label}${ms}`, tone };
    }
    case "run.completed": {
      const o = d.outcome as RunOutcome | undefined;
      const tone = o === "matched" ? "amber" : o === "error" || o === "blocked" ? "err" : "ok";
      const parts = [o ? OUTCOME_LABEL[o] : "Check finished"];
      if (d.llm_called === false) parts.push("AI skipped");
      // Unchanged pages already explained themselves in the step above; don't repeat the reason.
      const why = d.reason && o !== "skipped_unchanged" ? ` ${String(d.reason).slice(0, 140)}` : "";
      return { ...base, text: `${parts.join(" · ")}.${why}`, tone };
    }
    case "watch.scheduled":
      return d.next_run_at ? { ...base, text: `Next check ${relativeTime(String(d.next_run_at))}.`, tone: "dim" } : null;
    case "act.started":
      return { ...base, text: "Doing follow-up work on the alert…" };
    case "act.completed":
      return { ...base, text: `Follow-up ${d.status === "completed" ? "complete" : String(d.status || "done")}${d.actions ? ` · ${d.actions} action(s) to approve` : ""}.`, tone: "ok" };
    case "watch.refined":
      return { ...base, text: "Self-tuning applied a new version.", tone: "amber" };
    case "feedback.recorded":
      return { ...base, text: "Feedback recorded.", tone: "dim" };
    default:
      return null;
  }
}

function linesFromRun(run: RunDetail): LogLine[] {
  const out: LogLine[] = [{ key: `${run.id}-s`, at: run.started_at, text: run.trigger === "manual" ? "Starting manual check…" : "Starting scheduled check…", runId: run.id }];
  for (const [k, s] of (run.steps || []).entries()) {
    out.push({
      key: `${run.id}-${k}`,
      at: s.at || run.started_at,
      text: s.note || NODE_LABEL[s.node] || s.node,
      tone: s.status === "error" ? "err" : s.node === "fire" ? "amber" : s.status === "skipped" ? "dim" : undefined,
      runId: run.id,
    });
  }
  if (run.finished_at && run.outcome) {
    out.push({
      key: `${run.id}-c`,
      at: run.finished_at,
      text: `${OUTCOME_LABEL[run.outcome]}${run.llm_called ? "" : " · AI skipped"}. ${run.duration_ms ? `Check completed in ${(run.duration_ms / 1000).toFixed(1)}s.` : ""}`,
      tone: run.outcome === "matched" ? "amber" : run.outcome === "error" || run.outcome === "blocked" ? "err" : "ok",
      runId: run.id,
    });
  }
  return out;
}

/** Collects live events for a watch (with recent history replayed by the stream) into log lines. */
export function useLiveLog(watchId: string, lastRun: RunDetail | null | undefined) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const onEvent = useCallback(
    (e: LiveEvent) => {
      if (e.scope !== "watch" || e.stream !== watchId) return;
      if (e.type === "run.started") setRunning(true);
      if (e.type === "run.completed") setRunning(false);
      const l = lineFromEvent(e);
      if (l) setLines((prev) => (prev.some((p) => p.key === l.key) ? prev : [...prev, l].slice(-200)));
    },
    [watchId],
  );
  const status = useWatchStream(watchId, onEvent);
  const seeded = useMemo(() => (lastRun ? linesFromRun(lastRun) : []), [lastRun]);
  // Fall back to the last run's recorded steps when the stream has no history yet.
  const all = lines.length ? lines : seeded;
  return { lines: all, running, status };
}

export function LiveLog({ lines, running, status, className }: { lines: LogLine[]; running: boolean; status: StreamStatus; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (el && stick) el.scrollTop = el.scrollHeight;
  }, [lines, stick]);
  const lastRunId = [...lines].reverse().find((l) => l.runId)?.runId;

  return (
    <div className={className}>
      <div className="flex items-center justify-between">
        <div className="label-mono text-ink-2">
          <div className="text-ink-3">[02]</div>
          Live activity log
        </div>
        <span className="label-mono flex items-center gap-2 text-ink-2" role="status" aria-live="polite">
          <span className={cn("h-2 w-2 rounded-full", running ? "animate-blink bg-amber" : status === "live" ? "bg-ok-dot" : status === "connecting" ? "bg-amber" : "bg-err-dot")} />
          {running ? "Checking" : status === "live" ? "Live" : status === "connecting" ? "Connecting" : "Offline"}
        </span>
      </div>
      <div
        ref={ref}
        onScroll={(e) => {
          const el = e.currentTarget;
          setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
        }}
        className="ticked mono-tight mt-4 h-[360px] overflow-y-auto overflow-x-hidden border border-line-strong bg-bg/60 px-4 py-3 text-[12px] leading-[1.95]"
        role="log"
        aria-label="Live activity log"
        tabIndex={0}
      >
        {lines.length === 0 ? (
          <p className="py-10 text-center text-ink-3">Waiting for the next check. Steps appear here as they happen.</p>
        ) : (
          <AnimatePresence initial={false}>
            {lines.map((l, k) => {
              const prev = lines[k - 1];
              const newRun = prev && l.runId && prev.runId && l.runId !== prev.runId;
              const faded = lastRunId && l.runId && l.runId !== lastRunId;
              return (
                <motion.div key={l.key} initial={{ opacity: 0, x: -6 }} animate={{ opacity: faded ? 0.55 : 1, x: 0 }} transition={{ duration: 0.22 }}>
                  {newRun && <div className="my-2 border-t border-dashed border-line" aria-hidden />}
                  <div className="flex gap-4">
                    <span className="shrink-0 text-ink-3">{formatClock(l.at)}</span>
                    <span className={cn("min-w-0 break-words", l.tone === "ok" && "text-ok", l.tone === "amber" && "text-amber-ink", l.tone === "err" && "text-err", l.tone === "dim" && "text-ink-3", !l.tone && "text-ink")}>{l.text}</span>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
        {running && <span className="inline-block h-3.5 w-2 animate-blink bg-ink align-middle" aria-hidden />}
      </div>
    </div>
  );
}
