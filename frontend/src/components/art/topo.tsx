import { cn } from "@/lib/utils";

import { contourRings, rng } from "./geometry";

const FIELDS = [
  contourRings({ seed: 3, cx: 140, cy: 160, rings: 11, gap: 22, wobble: 0.16 }),
  contourRings({ seed: 9, cx: 760, cy: 120, rings: 9, gap: 26, wobble: 0.12, squash: 0.7 }),
  contourRings({ seed: 15, cx: 560, cy: 640, rings: 13, gap: 24, wobble: 0.18 }),
  contourRings({ seed: 21, cx: 1180, cy: 520, rings: 10, gap: 28, wobble: 0.15, squash: 0.9 }),
].flat();

const STARS = (() => {
  const r = rng(5);
  return Array.from({ length: 34 }, () => ({ x: r() * 1400, y: r() * 900, s: r() < 0.2 ? 1.6 : 0.9 }));
})();

/** Faint topographic contour field used behind sections (the designs' map texture). */
export function Topo({ className, stars = true }: { className?: string; stars?: boolean }) {
  return (
    <svg className={cn("pointer-events-none absolute inset-0 h-full w-full", className)} viewBox="0 0 1400 900" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <g fill="none" stroke="var(--topo)" strokeWidth="1">
        {FIELDS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      {stars && (
        <g fill="var(--ink)" fillOpacity="0.35">
          {STARS.map((s, i) => (
            <circle key={i} cx={s.x} cy={s.y} r={s.s} />
          ))}
        </g>
      )}
    </svg>
  );
}
