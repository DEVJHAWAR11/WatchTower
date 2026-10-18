"use client";

import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { useId, useRef } from "react";

import { cn } from "@/lib/utils";

import { pinePath, ridgePath, rng } from "./geometry";

const W = 900;
const H = 700;

// Precomputed once (deterministic).
const FAR = ridgePath({ seed: 11, x0: -40, x1: W + 40, base: 470, amp: 120, floor: H, scale: 0.0045, peaks: [{ x: 160, h: 90, w: 90 }, { x: 790, h: 70, w: 120 }] });
const MID = ridgePath({ seed: 23, x0: -40, x1: W + 40, base: 540, amp: 90, floor: H, scale: 0.006, peaks: [{ x: 300, h: 60, w: 110 }, { x: 860, h: 50, w: 80 }] });
const NEAR_L = ridgePath({ seed: 37, x0: -40, x1: 520, base: 620, amp: 60, floor: H, scale: 0.01, peaks: [{ x: 120, h: 40, w: 90 }] });
const NEAR_R = ridgePath({ seed: 41, x0: 680, x1: W + 40, base: 610, amp: 70, floor: H, scale: 0.012, peaks: [{ x: 840, h: 60, w: 70 }] });
// The observatory's peak: a broad massif rising to a flat shoulder at y≈452 under the tower.
const PEAK = ridgePath({
  seed: 53,
  x0: 330,
  x1: 900,
  base: 690,
  amp: 40,
  floor: H,
  scale: 0.014,
  step: 4,
  peaks: [
    { x: 600, h: 238, w: 120 },
    { x: 520, h: 120, w: 70 },
    { x: 690, h: 130, w: 80 },
    { x: 780, h: 60, w: 60 },
  ],
});

const TREES = (() => {
  const r = rng(77);
  const out: { d: string; o: number }[] = [];
  const spots: [number, number, number][] = [];
  for (let i = 0; i < 26; i++) spots.push([360 + r() * 170, 600 + r() * 90, 26 + r() * 30]);
  for (let i = 0; i < 22; i++) spots.push([690 + r() * 200, 590 + r() * 100, 24 + r() * 30]);
  for (let i = 0; i < 18; i++) spots.push([-10 + r() * 300, 640 + r() * 60, 30 + r() * 34]);
  spots.sort((a, b) => a[1] - b[1]);
  spots.forEach(([x, y, h], i) => out.push({ d: pinePath(x, y, h, i + 3), o: 0.55 + (y - 590) / 260 }));
  return out;
})();

const ROCKS = (() => {
  const r = rng(91);
  const out: string[] = [];
  for (let i = 0; i < 40; i++) {
    const x = 470 + r() * 280;
    const y = 470 + r() * 150;
    const w = 6 + r() * 18;
    out.push(`M${x.toFixed(1)},${y.toFixed(1)} l${w.toFixed(1)},${(-2 - r() * 3).toFixed(1)} l${(w * 0.4).toFixed(1)},${(4 + r() * 3).toFixed(1)}`);
  }
  return out.join(" ");
})();

function Observatory() {
  const cx = 600;
  const posts = Array.from({ length: 15 }, (_, i) => 548 + i * 7.4);
  return (
    <g>
      {/* lower block */}
      <path d={`M${cx - 44},458 L${cx - 40},398 L${cx + 40},398 L${cx + 44},458 Z`} fill="var(--scene)" fillOpacity="0.82" />
      <path d={`M${cx + 6},398 L${cx + 40},398 L${cx + 44},458 L${cx + 8},458 Z`} fill="var(--scene)" fillOpacity="0.25" />
      {[-30, -16, 12, 26].map((dx) => (
        <rect key={dx} x={cx + dx} y={412} width={6} height={13} fill="var(--scene-window)" fillOpacity="0.55" />
      ))}
      {[-30, -16, 12, 26].map((dx) => (
        <rect key={`b${dx}`} x={cx + dx} y={433} width={6} height={13} fill="var(--scene-window)" fillOpacity="0.4" />
      ))}
      <rect x={cx - 6} y={430} width={12} height={28} fill="var(--bg)" fillOpacity="0.6" />
      {/* balcony */}
      <rect x={cx - 54} y={390} width={108} height={8} fill="var(--scene)" fillOpacity="0.9" />
      <rect x={cx - 54} y={376} width={108} height={1.6} fill="var(--scene)" fillOpacity="0.85" />
      {posts.map((x) => (
        <rect key={x} x={x} y={377} width={1.2} height={13} fill="var(--scene)" fillOpacity="0.8" />
      ))}
      {/* drum */}
      <rect x={cx - 36} y={338} width={72} height={52} fill="var(--scene)" fillOpacity="0.78" />
      <rect x={cx + 6} y={338} width={30} height={52} fill="var(--scene)" fillOpacity="0.22" />
      {[-26, -12, 10, 22].map((dx) => (
        <rect key={dx} x={cx + dx} y={350} width={5} height={16} rx={2.5} fill="var(--scene-window)" fillOpacity="0.6" />
      ))}
      <rect x={cx - 40} y={334} width={80} height={5} fill="var(--scene)" fillOpacity="0.9" />
      {/* dome */}
      <path d={`M${cx - 37},334 A37,36 0 0 1 ${cx + 37},334 Z`} fill="url(#wt-dome)" />
      <path d={`M${cx - 37},334 A37,36 0 0 1 ${cx + 37},334`} fill="none" stroke="var(--scene)" strokeOpacity="0.55" strokeWidth="1.2" />
      {[-24, -10, 6, 20].map((dx) => (
        <path key={dx} d={`M${cx + dx},334 Q${cx + dx * 0.7},${312} ${cx + dx * 0.25},300`} fill="none" stroke="var(--scene)" strokeOpacity="0.28" strokeWidth="0.8" />
      ))}
      <path d={`M${cx - 4},334 L${cx - 3},300 L${cx + 5},300 L${cx + 6},334 Z`} fill="var(--scene)" fillOpacity="0.55" />
      <rect x={cx - 1.5} y={292} width={3} height={8} fill="var(--scene)" fillOpacity="0.7" />
      {/* steps down the slope */}
      {Array.from({ length: 9 }, (_, i) => (
        <rect key={i} x={cx + 46 + i * 9} y={452 + i * 6} width={10} height={2.2} fill="var(--scene)" fillOpacity={0.6 - i * 0.04} />
      ))}
    </g>
  );
}

export function ObservatoryScene({ className, glow = true, parallax = true }: { className?: string; glow?: boolean; parallax?: boolean }) {
  const id = useId().replace(/:/g, "");
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const on = parallax && !reduce;
  const yFar = useTransform(scrollYProgress, [0, 1], on ? [-10, 50] : [0, 0]);
  const yMid = useTransform(scrollYProgress, [0, 1], on ? [-6, 32] : [0, 0]);
  const yPeak = useTransform(scrollYProgress, [0, 1], on ? [0, 12] : [0, 0]);
  const yNear = useTransform(scrollYProgress, [0, 1], on ? [8, -24] : [0, 0]);

  return (
    <div ref={ref} className={cn("h-full w-full", className)}>
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" preserveAspectRatio="xMidYMax slice" aria-hidden>
      <defs>
        <radialGradient id={`${id}-glow`} cx="0.66" cy="0.62" r="0.55">
          <stop offset="0" stopColor="var(--amber)" stopOpacity="0.55" />
          <stop offset="0.45" stopColor="var(--amber)" stopOpacity="0.16" />
          <stop offset="1" stopColor="var(--amber)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-fog`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--bg)" stopOpacity="0" />
          <stop offset="1" stopColor="var(--bg)" stopOpacity="0.95" />
        </linearGradient>
        <linearGradient id={`${id}-peak`} x1="0" y1="0" x2="1" y2="0.4">
          <stop offset="0" stopColor="var(--scene)" stopOpacity="0.7" />
          <stop offset="0.55" stopColor="var(--scene)" stopOpacity="0.5" />
          <stop offset="1" stopColor="var(--scene)" stopOpacity="0.78" />
        </linearGradient>
        <linearGradient id="wt-dome" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="var(--scene-hi)" stopOpacity="0.95" />
          <stop offset="0.55" stopColor="var(--line-strong)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--scene)" stopOpacity="0.55" />
        </linearGradient>
        <pattern id={`${id}-hatch`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-35)">
          <line x1="0" y1="0" x2="0" y2="5" stroke="var(--bg)" strokeOpacity="0.35" strokeWidth="1" />
        </pattern>
        <clipPath id={`${id}-peakclip`}>
          <path d={PEAK} />
        </clipPath>
      </defs>

      {glow && <rect width={W} height={H} fill={`url(#${id}-glow)`} />}

      <motion.g style={{ y: yFar }}>
        <path d={FAR} fill="var(--scene)" fillOpacity="0.1" />
      </motion.g>
      <motion.g style={{ y: yMid }}>
        <path d={MID} fill="var(--scene)" fillOpacity="0.17" />
        <rect y={500} width={W} height={200} fill={`url(#${id}-fog)`} opacity="0.55" />
      </motion.g>

      <motion.g style={{ y: yPeak }}>
        <path d={PEAK} fill={`url(#${id}-peak)`} />
        <g clipPath={`url(#${id}-peakclip)`}>
          <rect x={330} y={420} width={570} height={280} fill={`url(#${id}-hatch)`} />
          <path d={ROCKS} fill="none" stroke="var(--bg)" strokeOpacity="0.35" strokeWidth="1" />
        </g>
        <Observatory />
      </motion.g>

      <motion.g style={{ y: yNear }}>
        <path d={NEAR_L} fill="var(--scene)" fillOpacity="0.55" />
        <path d={NEAR_R} fill="var(--scene)" fillOpacity="0.5" />
        {TREES.map((t, i) => (
          <path key={i} d={t.d} fill="var(--scene)" fillOpacity={Math.min(0.92, t.o)} />
        ))}
      </motion.g>
      <rect y={H - 120} width={W} height={120} fill={`url(#${id}-fog)`} />
    </svg>
    </div>
  );
}
