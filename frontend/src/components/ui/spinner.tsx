import { cn } from "@/lib/utils";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <svg className={cn("h-5 w-5 animate-spin", className)} viewBox="0 0 24 24" fill="none" role="status" aria-label={label}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

/** Full-area loader used while a page's first query resolves. */
export function PageLoader({ label = "Loading" }: { label?: string }) {
  return (
    <div className="grid min-h-[40vh] place-items-center text-ink-3" role="status" aria-live="polite">
      <div className="flex flex-col items-center gap-3">
        <RadarMini />
        <span className="label-mono">{label}…</span>
      </div>
    </div>
  );
}

export function RadarMini({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-block h-10 w-10", className)} aria-hidden>
      <span className="absolute inset-0 rounded-full border border-line-strong" />
      <span className="absolute inset-[30%] rounded-full border border-line" />
      <span
        className="absolute inset-0 animate-sweep rounded-full"
        style={{ background: "conic-gradient(from 0deg, transparent 0deg, transparent 300deg, var(--amber) 360deg)", opacity: 0.55 }}
      />
      <span className="absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink" />
    </span>
  );
}
