// Deterministic generators for the illustration paths (identical on server and client).

export function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Smooth 1D value noise, summed over octaves. */
export function noise1d(seed: number) {
  const r = rng(seed);
  const table = Array.from({ length: 256 }, () => r());
  const smooth = (t: number) => t * t * (3 - 2 * t);
  const at = (x: number) => {
    const i = Math.floor(x);
    const f = x - i;
    const a = table[((i % 256) + 256) % 256];
    const b = table[(((i + 1) % 256) + 256) % 256];
    return a + (b - a) * smooth(f);
  };
  return (x: number, octaves = 4) => {
    let amp = 1;
    let freq = 1;
    let sum = 0;
    let norm = 0;
    for (let o = 0; o < octaves; o++) {
      sum += at(x * freq) * amp;
      norm += amp;
      amp *= 0.5;
      freq *= 2.1;
    }
    return sum / norm;
  };
}

/** A mountain ridge as a closed path from x0 to x1, filled down to `floor`. */
export function ridgePath(opts: {
  seed: number;
  x0: number;
  x1: number;
  base: number;
  amp: number;
  floor: number;
  scale?: number;
  peaks?: { x: number; h: number; w: number }[];
  step?: number;
}): string {
  const n = noise1d(opts.seed);
  const step = opts.step ?? 6;
  const pts: string[] = [];
  for (let x = opts.x0; x <= opts.x1 + 0.1; x += step) {
    let y = opts.base - n(x * (opts.scale ?? 0.006), 5) * opts.amp;
    for (const p of opts.peaks ?? []) {
      const d = (x - p.x) / p.w;
      y -= p.h * Math.exp(-d * d);
    }
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return `M${opts.x0},${opts.floor} L${pts.join(" L")} L${opts.x1},${opts.floor} Z`;
}

/** Concentric, wobbly closed contours around a centre (topographic map look). */
export function contourRings(opts: { seed: number; cx: number; cy: number; rings: number; gap: number; wobble?: number; squash?: number }): string[] {
  const r = rng(opts.seed);
  const phases = [r() * 6.28, r() * 6.28, r() * 6.28];
  const out: string[] = [];
  for (let k = 1; k <= opts.rings; k++) {
    const base = k * opts.gap;
    const pts: string[] = [];
    const steps = 72;
    for (let i = 0; i <= steps; i++) {
      const th = (i / steps) * Math.PI * 2;
      const w = opts.wobble ?? 0.14;
      const rr =
        base *
        (1 +
          w * Math.sin(3 * th + phases[0] + k * 0.15) +
          w * 0.6 * Math.sin(5 * th + phases[1] - k * 0.1) +
          w * 0.35 * Math.sin(2 * th + phases[2]));
      const x = opts.cx + rr * Math.cos(th);
      const y = opts.cy + rr * Math.sin(th) * (opts.squash ?? 0.8);
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    out.push(`M${pts.join(" L")}Z`);
  }
  return out;
}

/** A pine tree silhouette at (x, y) with height h. */
export function pinePath(x: number, y: number, h: number, seed = 1): string {
  const r = rng(seed);
  const tiers = 4 + Math.floor(r() * 2);
  const w = h * 0.36;
  let d = `M${x - 0.8},${y} L${x - 0.8},${y - h * 0.12} L${x + 0.8},${y - h * 0.12} L${x + 0.8},${y} Z`;
  for (let i = 0; i < tiers; i++) {
    const t = i / tiers;
    const by = y - h * 0.1 - t * h * 0.82;
    const bw = w * (1 - t * 0.78) * (0.9 + r() * 0.2);
    const ty = by - h * 0.3;
    d += ` M${(x - bw).toFixed(1)},${by.toFixed(1)} L${x.toFixed(1)},${ty.toFixed(1)} L${(x + bw).toFixed(1)},${by.toFixed(1)} Z`;
  }
  return d;
}
