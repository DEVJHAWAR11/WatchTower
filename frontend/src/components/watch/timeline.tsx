"use client";

import { motion } from "motion/react";
import { useMemo, useState } from "react";

import { OUTCOME_LABEL } from "@/components/app/outcome";
import { NativeSelect } from "@/components/ui/field";
import { Tooltip } from "@/components/ui/primitives";
import type { Run } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

const RANGES = [
  { v: 24, label: "Last 24 hours" },
  { v: 72, label: "Last 3 days" },
  { v: 168, label: "Last 7 days" },
];

function kind(r: Run): "none" | "changed" | "triggered" | "error" {
  if (r.outcome === "matched") return "triggered";
  if (r.outcome === "error" || r.outcome === "blocked") return "error";
  if (r.outcome === "no_match" || r.outcome === "duplicate") return "changed";
  return "none";
}

const DOT: Record<string, string> = {
  none: "bg-line-strong",
  changed: "bg-ok-dot",
  triggered: "bg-amber",
  error: "bg-err-dot",
};

/** Dot timeline of checks; click a dot to inspect that run. */
export function CheckTimeline({ runs, onSelect, loading }: { runs: Run[]; onSelect: (r: Run) => void; loading?: boolean }) {
  const [hours, setHours] = useState(24);
  const [now] = useState(() => Date.now());
  const from = now - hours * 3600_000;
  const inRange = useMemo(() => runs.filter((r) => new Date(r.started_at).getTime() >= from).sort((a, b) => a.started_at.localeCompare(b.started_at)), [runs, from]);
  const ticks = Array.from({ length: 5 }, (_, i) => from + ((now - from) * i) / 4);
  const pos = (iso: string) => ((new Date(iso).getTime() - from) / (now - from)) * 100;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="label-mono text-ink-2">
          <div className="text-ink-3">[01]</div>
          Check timeline
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2" aria-label="Legend">
            {[
              ["none", "No change"],
              ["changed", "Changed (not relevant)"],
              ["triggered", "Triggered"],
              ["error", "Error"],
            ].map(([k, l]) => (
              <li key={k} className="flex items-center gap-1.5">
                <span className={cn("h-2 w-2 rounded-full", DOT[k])} aria-hidden /> {l}
              </li>
            ))}
          </ul>
          <NativeSelect aria-label="Time range" value={hours} onChange={(e) => setHours(Number(e.target.value))} className="h-9 w-40 text-[13px]">
            {RANGES.map((r) => (
              <option key={r.v} value={r.v}>
                {r.label}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className="relative mt-8 h-16">
        <div className="absolute inset-x-0 top-3 h-px bg-line-strong" aria-hidden />
        {loading && <div className="skeleton absolute inset-x-0 top-2 h-2" />}
        {!loading && inRange.length === 0 && <p className="absolute inset-x-0 top-6 text-center text-[13px] text-ink-3">No checks in this period.</p>}
        <ul aria-label={`${inRange.length} checks`}>
          {inRange.map((r, i) => {
            const k = kind(r);
            const big = k === "triggered";
            return (
              <li key={r.id} className="absolute top-3 -translate-x-1/2 -translate-y-1/2" style={{ left: `${Math.min(99, Math.max(1, pos(r.started_at)))}%` }}>
                <Tooltip content={`${formatDateTime(r.started_at)} · ${r.outcome ? OUTCOME_LABEL[r.outcome] : "Running"}`}>
                  <motion.button
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: Math.min(i * 0.015, 0.6) }}
                    onClick={() => onSelect(r)}
                    className={cn("block rounded-full ring-bg transition-transform hover:scale-150 focus-visible:scale-150", DOT[k], big ? "h-4 w-4 ring-2" : "h-2.5 w-2.5")}
                    aria-label={`Check at ${formatDateTime(r.started_at)}: ${r.outcome ? OUTCOME_LABEL[r.outcome] : "running"}`}
                  />
                </Tooltip>
              </li>
            );
          })}
        </ul>
        <div className="absolute inset-x-0 top-8 flex justify-between" aria-hidden>
          {ticks.map((t, i) => (
            <span key={t} className={cn("mono-tight text-[10.5px] leading-tight text-ink-3", i === 4 ? "text-right" : i === 0 ? "" : "text-center")}>
              {i === 4 ? (
                "Now"
              ) : (
                <>
                  {new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  <br />
                  {new Date(t).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                </>
              )}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
