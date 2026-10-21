import { AlertTriangle, RotateCw } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/** "[01]  TELL US WHAT TO WATCH" */
export function SectionLabel({ index, children, className, as: As = "div" }: { index?: string | number; children: React.ReactNode; className?: string; as?: "div" | "h2" | "h3" | "p" }) {
  return (
    <As className={cn("label-mono flex flex-col gap-1.5 text-ink-2", className)}>
      {index !== undefined && <span className="tracking-[0.2em] text-ink-3">[{typeof index === "number" ? String(index).padStart(2, "0") : index}]</span>}
      <span>{children}</span>
    </As>
  );
}

export function Card({ className, children, ticked = true, ...props }: React.HTMLAttributes<HTMLDivElement> & { ticked?: boolean }) {
  return (
    <div className={cn("border border-line bg-elevated/70", ticked && "ticked", className)} {...props}>
      {children}
    </div>
  );
}

const badgeTones = {
  neutral: "border-line-strong/70 text-ink-2 bg-transparent",
  solid: "border-transparent bg-sunken text-ink-2",
  amber: "border-amber/50 bg-amber-soft text-amber-ink",
  ok: "border-ok/30 bg-ok-soft text-ok",
  err: "border-err/30 bg-err-soft text-err",
  ink: "border-transparent bg-ink text-bg",
} as const;

export function Badge({ tone = "neutral", className, children, mono = true }: { tone?: keyof typeof badgeTones; className?: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-[2px] border px-2",
        mono ? "font-mono text-[10.5px] uppercase tracking-[0.1em]" : "text-xs",
        badgeTones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export type DotTone = "ok" | "amber" | "err" | "idle" | "info";
const dotColor: Record<DotTone, string> = {
  ok: "bg-ok-dot",
  amber: "bg-amber",
  err: "bg-err-dot",
  idle: "bg-line-strong",
  info: "bg-info",
};

export function StatusDot({ tone = "ok", pulse, className, label }: { tone?: DotTone; pulse?: boolean; className?: string; label?: string }) {
  return (
    <span className={cn("relative inline-flex h-2.5 w-2.5 shrink-0", className)} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {pulse && <span className={cn("absolute inset-0 animate-ping-slow rounded-full", dotColor[tone])} />}
      <span className={cn("relative inline-flex h-full w-full rounded-full", dotColor[tone])} />
    </span>
  );
}

/** Bar sparkline in the "activity" style of the dashboard designs. */
export function Sparkbars({
  values,
  highlight,
  tone = "ok",
  className,
  height = 22,
  label,
}: {
  values: number[];
  highlight?: boolean[];
  tone?: "ok" | "amber" | "err" | "ink";
  className?: string;
  height?: number;
  label?: string;
}) {
  const max = Math.max(1, ...values);
  const color = { ok: "var(--ok-dot)", amber: "var(--amber)", err: "var(--err-dot)", ink: "var(--ink-3)" }[tone];
  const w = values.length * 6;
  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      width={w}
      height={height}
      className={cn("shrink-0 overflow-visible", className)}
      role="img"
      aria-label={label || `Activity: ${values.join(", ")}`}
    >
      {values.map((v, i) => {
        const h = v === 0 ? 2 : Math.max(3, (v / max) * height);
        const hl = highlight?.[i];
        return (
          <rect
            key={i}
            x={i * 6}
            y={height - h}
            width={3.2}
            height={h}
            rx={0.6}
            fill={hl ? "var(--amber)" : color}
            opacity={v === 0 ? 0.35 : hl ? 1 : 0.55 + 0.45 * (v / max)}
          />
        );
      })}
    </svg>
  );
}

/** Tiny decorative bars for stat tiles (deterministic from a seed so SSR and client agree). */
export function NoiseBars({ seed = 1, n = 18, className }: { seed?: number; n?: number; className?: string }) {
  const vals: number[] = [];
  let x = seed * 9301 + 49297;
  for (let i = 0; i < n; i++) {
    x = (x * 9301 + 49297) % 233280;
    vals.push(0.2 + (x / 233280) * (0.45 + i / n));
  }
  return (
    <svg viewBox={`0 0 ${n * 5} 24`} className={cn("h-6 w-auto text-ink-3", className)} aria-hidden>
      {vals.map((v, i) => (
        <rect key={i} x={i * 5} y={24 - v * 24} width={1.6} height={v * 24} fill="currentColor" opacity={0.35 + v * 0.5} />
      ))}
    </svg>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  body?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("ticked flex flex-col items-center border border-dashed border-line-strong/80 px-6 py-14 text-center", className)}>
      {icon && <div className="mb-4 text-ink-3 [&>svg]:h-8 [&>svg]:w-8">{icon}</div>}
      <h3 className="font-display text-2xl text-ink">{title}</h3>
      {body && <div className="mt-2 max-w-md text-sm text-ink-2">{body}</div>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Couldn't load this",
  error,
  onRetry,
  className,
}: {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const message =
    error && typeof error === "object" && "message" in error ? String((error as { message: string }).message) : "Something went wrong.";
  const rid = error && typeof error === "object" && "requestId" in error ? (error as { requestId?: string }).requestId : undefined;
  return (
    <div role="alert" className={cn("flex flex-col items-center gap-3 border border-err/30 bg-err-soft/50 px-6 py-10 text-center", className)}>
      <AlertTriangle className="h-6 w-6 text-err" aria-hidden />
      <div>
        <p className="font-medium text-ink">{title}</p>
        <p className="mt-1 text-sm text-ink-2">{message}</p>
        {rid && <p className="label-mono mt-2 normal-case tracking-normal text-ink-3">Ref: {rid}</p>}
      </div>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-2 text-sm font-medium text-ink underline underline-offset-4">
          <RotateCw className="h-3.5 w-3.5" /> Try again
        </button>
      )}
    </div>
  );
}

export function Meter({ value, max, label, format }: { value: number; max: number; label: string; format?: (n: number) => string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const tone = pct >= 100 ? "bg-err-dot" : pct >= 80 ? "bg-amber" : "bg-ok-dot";
  const f = format || ((n: number) => n.toLocaleString("en-IN"));
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-ink-2">{label}</span>
        <span className="mono-tight text-[12.5px] text-ink">
          {f(value)} <span className="text-ink-3">/ {max >= 100000 && label.toLowerCase().includes("subscr") ? "∞" : f(max)}</span>
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
        <div className={cn("h-full rounded-full transition-[width] duration-700", tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** "+" registration mark used across the designs. */
export function Crosshair({ className, size = 28 }: { className?: string; size?: number }) {
  return (
    <svg className={cn("pointer-events-none text-line-strong", className)} width={size} height={size} viewBox="0 0 28 28" aria-hidden>
      <path d="M14 0v28M0 14h28" stroke="currentColor" strokeWidth="0.8" />
    </svg>
  );
}

export function Coordinates({ className }: { className?: string }) {
  return (
    <div className={cn("label-mono text-[10px] leading-relaxed text-ink-3", className)} aria-hidden>
      28.6139° N
      <br />
      77.2090° E
    </div>
  );
}

export function Kicker({ lines, className }: { lines: string[]; className?: string }) {
  return (
    <div className={cn("label-mono text-[10px] leading-[1.8] text-ink-3", className)} aria-hidden>
      {lines.map((l) => (
        <div key={l}>{l}</div>
      ))}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}
