"use client";

import { useEffect, useState } from "react";

import { StatusDot } from "@/components/ui/display";
import { cn } from "@/lib/utils";

type S = "checking" | "operational" | "degraded" | "unreachable";
const TEXT: Record<S, string> = {
  checking: "System status / checking",
  operational: "System status / all systems operational",
  degraded: "System status / partially degraded",
  unreachable: "System status / reconnecting",
};

/** Live API health, polled every minute. */
export function SystemStatus({ className }: { className?: string }) {
  const [s, setS] = useState<S>("checking");
  useEffect(() => {
    let alive = true;
    const run = () =>
      fetch("/api/health", { cache: "no-store" })
        .then((r) => r.json())
        .then((d) => alive && setS(d.status as S))
        .catch(() => alive && setS("unreachable"));
    run();
    const t = setInterval(run, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const tone = s === "operational" ? "ok" : s === "checking" ? "idle" : s === "degraded" ? "amber" : "err";
  return (
    <div className={cn("label-mono flex items-center gap-3 text-ink-2", className)} role="status" aria-live="polite">
      <StatusDot tone={tone} pulse={s === "operational"} />
      {TEXT[s]}
    </div>
  );
}
