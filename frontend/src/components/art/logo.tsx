import Link from "next/link";

import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={cn("h-8 w-8", className)} aria-hidden>
      <path d="M20 2 38 20 20 38 2 20Z" fill="none" stroke="var(--ink)" strokeWidth="3.2" strokeLinejoin="miter" />
      {/* four-point compass star; the north-east quadrant carries the accent */}
      <path d="M20 8 23 17 32 20 23 23 20 32 17 23 8 20 17 17Z" fill="var(--ink)" />
      <path d="M20 8 23 17 32 20 20 20Z" fill="var(--amber)" />
      <circle cx="20" cy="20" r="1.6" fill="var(--bg)" />
    </svg>
  );
}

export function Logo({ className, href = "/", compact }: { className?: string; href?: string; compact?: boolean }) {
  return (
    <Link href={href} className={cn("group inline-flex items-center gap-2.5 text-ink", className)} aria-label="Watchtower home">
      <LogoMark className="transition-transform duration-500 group-hover:rotate-45" />
      {!compact && <span className="font-display text-[26px] leading-none tracking-[-0.02em]">Watchtower</span>}
    </Link>
  );
}
