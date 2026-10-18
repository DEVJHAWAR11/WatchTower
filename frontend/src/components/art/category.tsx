import {
  Award,
  Briefcase,
  CalendarDays,
  Cpu,
  Eye,
  FileText,
  GraduationCap,
  Landmark,
  Newspaper,
  Package,
  School,
  Tag,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { contourRings, noise1d, rng } from "./geometry";

export const CATEGORY_META: Record<string, { icon: LucideIcon; label: string; motif: Motif }> = {
  jobs: { icon: Briefcase, label: "Jobs", motif: "grid" },
  placements: { icon: GraduationCap, label: "Placements", motif: "grid" },
  "exams-results": { icon: FileText, label: "Exams", motif: "columns" },
  admissions: { icon: School, label: "Admissions", motif: "columns" },
  scholarships: { icon: Award, label: "Scholarships", motif: "globe" },
  government: { icon: Landmark, label: "Government", motif: "columns" },
  ipo: { icon: TrendingUp, label: "IPOs", motif: "chart" },
  "price-drops": { icon: Tag, label: "Prices", motif: "chart" },
  restocks: { icon: Package, label: "Restocks", motif: "boxes" },
  "tech-releases": { icon: Cpu, label: "Tech", motif: "circuit" },
  news: { icon: Newspaper, label: "News", motif: "lines" },
  events: { icon: CalendarDays, label: "Events", motif: "topo" },
  other: { icon: Eye, label: "Other", motif: "topo" },
};

const KIND_TO_CATEGORY: Record<string, string> = {
  job: "jobs",
  exam_result: "exams-results",
  exam_notification: "exams-results",
  admission: "admissions",
  scholarship: "scholarships",
  ipo: "ipo",
  price_drop: "price-drops",
  restock: "restocks",
  release: "tech-releases",
  news: "news",
  event: "events",
  generic: "other",
};

export function categoryOf(slug?: string | null, kind?: string | null) {
  const key = slug && CATEGORY_META[slug] ? slug : KIND_TO_CATEGORY[kind || ""] || "other";
  return { slug: key, ...CATEGORY_META[key] };
}

export function CategoryIcon({ slug, kind, className }: { slug?: string | null; kind?: string | null; className?: string }) {
  const Icon = categoryOf(slug, kind).icon;
  return <Icon className={cn("h-5 w-5", className)} strokeWidth={1.5} aria-hidden />;
}

type Motif = "grid" | "columns" | "globe" | "chart" | "boxes" | "circuit" | "lines" | "topo";

function hash(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Engraved-style thumbnail for a watch card, varied per watch but stable. */
export function CategoryArt({ slug, kind, seed, className }: { slug?: string | null; kind?: string | null; seed: string; className?: string }) {
  const motif = categoryOf(slug, kind).motif;
  const h = hash(seed);
  const r = rng(h);
  const S = 100;
  let body: React.ReactNode = null;

  if (motif === "chart") {
    const n = noise1d(h);
    const pts = Array.from({ length: 26 }, (_, i) => `${(i * 4).toFixed(0)},${(78 - n(i * 0.35, 3) * 40 - i * 1.2).toFixed(1)}`);
    body = (
      <>
        {Array.from({ length: 9 }, (_, i) => (
          <line key={i} x1={i * 12.5} y1="0" x2={i * 12.5} y2={S} stroke="var(--ink)" strokeOpacity="0.12" strokeWidth="0.6" />
        ))}
        {Array.from({ length: 9 }, (_, i) => (
          <line key={`h${i}`} x1="0" y1={i * 12.5} x2={S} y2={i * 12.5} stroke="var(--ink)" strokeOpacity="0.12" strokeWidth="0.6" />
        ))}
        <polyline points={pts.join(" ")} fill="none" stroke="var(--ink)" strokeOpacity="0.75" strokeWidth="1.4" />
      </>
    );
  } else if (motif === "columns") {
    const cols = 5 + Math.floor(r() * 3);
    const w = 70 / cols;
    body = (
      <>
        <path d="M14 38 L50 18 L86 38 Z" fill="var(--ink)" fillOpacity="0.5" />
        <rect x="12" y="38" width="76" height="5" fill="var(--ink)" fillOpacity="0.6" />
        {Array.from({ length: cols }, (_, i) => (
          <rect key={i} x={15 + i * w + w * 0.2} y="45" width={w * 0.55} height="34" fill="var(--ink)" fillOpacity={0.35 + (i % 2) * 0.12} />
        ))}
        <rect x="8" y="80" width="84" height="5" fill="var(--ink)" fillOpacity="0.6" />
        <rect x="4" y="86" width="92" height="5" fill="var(--ink)" fillOpacity="0.45" />
      </>
    );
  } else if (motif === "globe") {
    body = (
      <g fill="none" stroke="var(--ink)" strokeOpacity="0.55" strokeWidth="0.8">
        <circle cx="50" cy="50" r="36" />
        {[12, 24, 36].map((rx) => (
          <ellipse key={rx} cx="50" cy="50" rx={rx} ry="36" />
        ))}
        {[-24, -12, 0, 12, 24].map((dy) => (
          <ellipse key={dy} cx="50" cy={50 + dy} rx={Math.sqrt(36 * 36 - dy * dy)} ry={3} />
        ))}
      </g>
    );
  } else if (motif === "boxes") {
    body = (
      <g>
        {Array.from({ length: 6 }, (_, i) => {
          const x = 12 + (i % 3) * 26;
          const y = 26 + Math.floor(i / 3) * 28;
          return <rect key={i} x={x} y={y} width="22" height="24" fill="var(--ink)" fillOpacity={0.25 + r() * 0.35} />;
        })}
      </g>
    );
  } else if (motif === "circuit") {
    body = (
      <g stroke="var(--ink)" strokeOpacity="0.55" strokeWidth="1" fill="none">
        {Array.from({ length: 8 }, (_, i) => {
          const y = 12 + i * 11;
          const x = 10 + r() * 30;
          return <path key={i} d={`M0 ${y} H${x} l8 8 H${60 + r() * 30}`} />;
        })}
        <rect x="36" y="36" width="28" height="28" fill="var(--ink)" fillOpacity="0.4" />
      </g>
    );
  } else if (motif === "lines") {
    body = (
      <g fill="var(--ink)">
        <rect x="10" y="12" width="80" height="8" fillOpacity="0.55" />
        {Array.from({ length: 9 }, (_, i) => (
          <rect key={i} x="10" y={28 + i * 7} width={40 + r() * 40} height="2.4" fillOpacity="0.3" />
        ))}
      </g>
    );
  } else if (motif === "grid") {
    body = (
      <g>
        {Array.from({ length: 30 }, (_, i) => {
          const x = (i % 6) * 16 + 4;
          const y = Math.floor(i / 6) * 18 + 6;
          const hgt = 6 + r() * 12;
          return <rect key={i} x={x} y={y + 12 - hgt} width="10" height={hgt} fill="var(--ink)" fillOpacity={0.15 + r() * 0.4} />;
        })}
      </g>
    );
  } else {
    body = (
      <g fill="none" stroke="var(--ink)" strokeOpacity="0.45" strokeWidth="0.7">
        {contourRings({ seed: h, cx: 30 + r() * 40, cy: 30 + r() * 40, rings: 9, gap: 7, wobble: 0.2 }).map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
    );
  }

  return (
    <svg viewBox={`0 0 ${S} ${S}`} className={cn("block bg-sunken", className)} preserveAspectRatio="xMidYMid slice" aria-hidden>
      {body}
    </svg>
  );
}
