import { cn } from "@/lib/utils";

import { rng } from "./geometry";

/** Round so server and browser trig agree exactly (avoids hydration mismatches). */
const f = (n: number) => Math.round(n * 100) / 100;

const PERIOD = 7; // seconds per sweep (matches --animate-sweep)

const BLIPS = (() => {
  const r = rng(7);
  return Array.from({ length: 16 }, (_, i) => {
    const ang = r() * 360;
    const rad = 0.22 + r() * 0.72;
    return { ang, rad, amber: i % 4 === 0, size: 1.6 + r() * 1.6 };
  });
})();

/**
 * The compass radar from the hero: range rings, bearings, orbit traces and a rotating sweep. Blips flash as the
 * beam passes them (pure CSS, so it costs nothing and stops under prefers-reduced-motion).
 */
export function Radar({ className, labels = true, size = 600 }: { className?: string; labels?: boolean; size?: number }) {
  const c = size / 2;
  const R = c * 0.82;
  const rings = [0.18, 0.36, 0.54, 0.72, 0.86, 1];
  const ticks = Array.from({ length: 72 }, (_, i) => i * 5);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className={cn("h-full w-full", className)} role="img" aria-label="Radar scanning the web for changes">
      <defs>
        <radialGradient id="wt-radar-fill" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="var(--ink)" stopOpacity="0.07" />
          <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="wt-sweep" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="var(--amber)" stopOpacity="0" />
          <stop offset="1" stopColor="var(--amber)" stopOpacity="0.55" />
        </linearGradient>
      </defs>
      <circle cx={c} cy={c} r={R} fill="url(#wt-radar-fill)" />
      {rings.map((k) => (
        <circle key={k} cx={c} cy={c} r={f(R * k)} fill="none" stroke="var(--ink)" strokeOpacity={k === 1 ? 0.55 : 0.16} strokeWidth={k === 1 ? 1.1 : 0.7} strokeDasharray={k === 0.86 ? "2 4" : undefined} />
      ))}
      {ticks.map((a) => {
        const rad = (a * Math.PI) / 180;
        const long = a % 30 === 0;
        const r1 = R;
        const r2 = R + (long ? 10 : 5);
        return (
          <line key={a} x1={f(c + r1 * Math.sin(rad))} y1={f(c - r1 * Math.cos(rad))} x2={f(c + r2 * Math.sin(rad))} y2={f(c - r2 * Math.cos(rad))} stroke="var(--ink)" strokeOpacity={long ? 0.6 : 0.3} strokeWidth="0.8" />
        );
      })}
      {[0, 30, 60, 90, 120, 150].map((a) => {
        const rad = (a * Math.PI) / 180;
        return <line key={a} x1={f(c - R * Math.sin(rad))} y1={f(c + R * Math.cos(rad))} x2={f(c + R * Math.sin(rad))} y2={f(c - R * Math.cos(rad))} stroke="var(--ink)" strokeOpacity={a % 90 === 0 ? 0.45 : 0.12} strokeWidth="0.7" strokeDasharray={a % 90 === 0 ? undefined : "1 5"} />;
      })}
      {/* orbit traces */}
      <ellipse cx={c} cy={c} rx={f(R * 1.12)} ry={f(R * 0.64)} fill="none" stroke="var(--ink)" strokeOpacity="0.28" strokeWidth="0.8" strokeDasharray="1.5 5" transform={`rotate(-28 ${c} ${c})`} />
      <ellipse cx={c} cy={c} rx={f(R * 0.92)} ry={f(R * 0.4)} fill="none" stroke="var(--ink)" strokeOpacity="0.2" strokeWidth="0.8" strokeDasharray="1.5 5" transform={`rotate(38 ${c} ${c})`} />

      {/* sweep */}
      <g className="origin-center animate-sweep" style={{ transformOrigin: `${c}px ${c}px`, transformBox: "view-box" }}>
        <path d={`M${c},${c} L${c},${f(c - R)} A${f(R)},${f(R)} 0 0 1 ${f(c + R * Math.SQRT1_2)},${f(c - R * Math.SQRT1_2)} Z`} fill="url(#wt-sweep)" />
        <line x1={c} y1={c} x2={f(c + R * Math.SQRT1_2)} y2={f(c - R * Math.SQRT1_2)} stroke="var(--amber)" strokeWidth="1.6" />
        <circle cx={f(c + R * Math.SQRT1_2)} cy={f(c - R * Math.SQRT1_2)} r="4" fill="var(--amber)" />
      </g>

      {BLIPS.map((b, i) => {
        const rad = (b.ang * Math.PI) / 180;
        const x = f(c + R * b.rad * Math.sin(rad));
        const y = f(c - R * b.rad * Math.cos(rad));
        // the beam's leading edge is at +45°; it reaches angle a after (a-45)/360 of a period
        const delay = (((b.ang - 45 + 360) % 360) / 360) * PERIOD;
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={f(b.size)}
            fill={b.amber ? "var(--amber)" : "var(--ink)"}
            className="wt-blip"
            style={{ animationDelay: `${f(delay)}s` }}
          />
        );
      })}
      <circle cx={c} cy={c} r="3.5" fill="var(--ink)" />
      <path d={`M${c - 10},${c} H${c + 10} M${c},${c - 10} V${c + 10}`} stroke="var(--ink)" strokeWidth="0.8" />

      {labels && (
        <g className="font-mono" fontSize={size * 0.024} fill="var(--ink)" fillOpacity="0.75" textAnchor="middle">
          <text x={c} y={c - R - 20}>N</text>
          <text x={c} y={c + R + 32}>S</text>
          <text x={c + R + 28} y={c + 5}>E</text>
          <text x={c - R - 28} y={c + 5}>W</text>
        </g>
      )}
    </svg>
  );
}
