import Link from "next/link";

import { Logo } from "@/components/art/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Kicker } from "@/components/ui/display";

const COLS = [
  {
    title: "Product",
    links: [
      { href: "/#how-it-works", label: "How it works" },
      { href: "/explore", label: "Community watches" },
      { href: "/pricing", label: "Pricing" },
      { href: "/signup", label: "Create an account" },
    ],
  },
  {
    title: "Popular",
    links: [
      { href: "/explore?category=exams-results", label: "Exam & result alerts" },
      { href: "/explore?category=jobs", label: "Job openings" },
      { href: "/explore?category=scholarships", label: "Scholarships" },
      { href: "/explore?category=price-drops", label: "Price drops" },
    ],
  },
  {
    title: "Developers & legal",
    links: [
      { href: "/docs", label: "API & webhooks" },
      { href: "/privacy", label: "Privacy" },
      { href: "/terms", label: "Terms" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="defer-paint relative border-t border-line">
      <div className="mx-auto grid max-w-[1440px] gap-12 px-4 py-16 sm:px-8 lg:grid-cols-[1.2fr_2fr] lg:px-12">
        <div className="space-y-5">
          <Logo />
          <p className="max-w-sm text-[15px] text-ink-2">
            AI agents that keep an eye on the web for you, so you hear about what matters the moment it happens.
          </p>
          <Kicker lines={["// monitor", "// analyze", "// alert"]} />
        </div>
        <div className="grid gap-10 sm:grid-cols-3">
          {COLS.map((c) => (
            <div key={c.title}>
              <h2 className="label-mono text-ink-3">{c.title}</h2>
              <ul className="mt-4 space-y-2.5">
                {c.links.map((l) => (
                  <li key={l.href}>
                    <Link href={l.href} className="text-[15px] text-ink-2 transition-colors hover:text-ink">
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-[1440px] flex-col items-start justify-between gap-4 px-4 py-6 sm:flex-row sm:items-center sm:px-8 lg:px-12">
          <p className="label-mono text-ink-3">© 2026 Watchtower · By people who stay curious.</p>
          <ThemeToggle />
        </div>
      </div>
    </footer>
  );
}
