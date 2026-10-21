"use client";

import {
  ArrowRight,
  Bell,
  Calendar,
  Check,
  Clock,
  CreditCard,
  Database,
  ExternalLink,
  FilePlus2,
  Globe2,
  Link2,
  Mail,
  Radar as RadarIcon,
  Send,
  Smartphone,
} from "lucide-react";
import { motion, useInView, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { CategoryArt } from "@/components/art/category";
import { ObservatoryScene } from "@/components/art/observatory";
import { Topo } from "@/components/art/topo";
import { Button } from "@/components/ui/button";
import { Coordinates, Crosshair, Kicker, NoiseBars, SectionLabel } from "@/components/ui/display";
import { cn, pad2 } from "@/lib/utils";

const ease = [0.2, 0.8, 0.2, 1] as const;

export function Reveal({ children, delay = 0, className, y = 18 }: { children: React.ReactNode; delay?: number; className?: string; y?: number }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.7, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

// ------------------------------------------------------------------ stats strip
function SchedulerTick() {
  const [s, setS] = useState(8);
  useEffect(() => {
    const t = setInterval(() => setS((x) => (x <= 0 ? 9 : x - 1)), 1000);
    return () => clearInterval(t);
  }, []);
  return <span suppressHydrationWarning>00:00:{pad2(s)}</span>;
}

export function StatsStrip() {
  const items = [
    { icon: Globe2, label: "Sources per watch", value: "Up to 5" },
    { icon: RadarIcon, label: "Fastest check", value: "15 min" },
    { icon: Bell, label: "Email, push, Telegram", value: "3 channels" },
    { icon: Clock, label: "Next scheduler sweep", value: <SchedulerTick /> },
  ];
  return (
    <section aria-label="At a glance" className="relative border-y border-line bg-bg">
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 divide-y divide-line sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
        {items.map((it, k) => (
          <div key={it.label} className="ticked flex items-center gap-5 px-6 py-6 sm:px-8 lg:px-10">
            <it.icon className="h-6 w-6 shrink-0 text-ink" strokeWidth={1.4} aria-hidden />
            <div className="min-w-0">
              <div className="label-mono text-[10px] text-ink-3">[{pad2(k + 1)}] {it.label}</div>
              <div className="mt-1 truncate font-display text-[26px] leading-tight text-ink sm:text-[30px]">{it.value}</div>
            </div>
            <NoiseBars seed={k + 3} className="ml-auto hidden xl:block" />
          </div>
        ))}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ how it works
const STEPS = [
  { icon: FilePlus2, title: "Describe it.", body: "Tell us what to watch: an exam, a company, a product, a keyword or any URL. English, Hindi or Hinglish." },
  { icon: RadarIcon, title: "Agent sets up the watch.", body: "It asks a quick question if needed, finds the official page, tests it live and proposes a plan you approve." },
  { icon: Database, title: "Checks quietly on schedule.", body: "Unchanged pages cost nothing. Rules decide simple cases; AI judges only real, relevant changes." },
  { icon: Bell, title: "Acts and alerts you.", body: "One complete alert with deadlines, links and next steps, by email, push or Telegram. Only when it matters." },
];

export function HowItWorks() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-120px" });
  return (
    <section id="how-it-works" aria-labelledby="how-title" className="defer-paint relative scroll-mt-20 overflow-hidden py-24 sm:py-32">
      <Topo stars={false} />
      <div className="relative mx-auto max-w-[1440px] px-4 sm:px-8 lg:px-12">
        <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr] lg:items-end">
          <Reveal>
            <SectionLabel index={2}>How it works</SectionLabel>
            <h2 id="how-title" className="mt-6 font-display text-[clamp(2.6rem,5.6vw,5rem)] leading-[0.95] text-ink">
              From intent to insight,
              <br />
              in <em className="accent">four simple steps.</em>
            </h2>
          </Reveal>
          <Reveal delay={0.1} className="flex items-end justify-between gap-6">
            <p className="max-w-md text-lg leading-relaxed text-ink-2">
              Set what you care about, and Watchtower keeps an eye on the web for you, quietly tracking changes and
              alerting you when it matters.
            </p>
            <div className="hidden text-right xl:block">
              <Coordinates />
              <Kicker className="mt-4" lines={["// monitor", "// analyze", "// alert"]} />
            </div>
          </Reveal>
        </div>

        <div ref={ref} className="relative mt-20">
          {/* connecting rule draws itself on scroll */}
          <svg className="absolute left-0 top-[52px] hidden h-2 w-full lg:block" preserveAspectRatio="none" viewBox="0 0 100 2" aria-hidden>
            <motion.line x1="12" y1="1" x2="88" y2="1" stroke="var(--line-strong)" strokeWidth="0.15" initial={{ pathLength: 0 }} animate={{ pathLength: inView ? 1 : 0 }} transition={{ duration: 1.6, ease }} />
          </svg>
          <ol className="grid gap-12 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
            {STEPS.map((s, k) => (
              <motion.li
                key={s.title}
                className="relative flex flex-col items-center text-center"
                initial={{ opacity: 0, y: 24 }}
                animate={inView ? { opacity: 1, y: 0 } : {}}
                transition={{ duration: 0.7, delay: 0.25 + k * 0.18, ease }}
              >
                <span className="label-mono text-ink-3">[{pad2(k + 1)}]</span>
                <div className="relative mt-3 grid h-[84px] w-[96px] place-items-center bg-bg">
                  <span className="absolute left-0 top-0 h-3 w-3 border-l border-t border-ink" />
                  <span className="absolute right-0 top-0 h-3 w-3 border-r border-t border-ink" />
                  <span className="absolute bottom-0 left-0 h-3 w-3 border-b border-l border-ink" />
                  <span className="absolute bottom-0 right-0 h-3 w-3 border-b border-r border-ink" />
                  <s.icon className="h-9 w-9 text-ink" strokeWidth={1.2} aria-hidden />
                  <span className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full bg-amber" aria-hidden />
                </div>
                <h3 className="mt-6 font-display text-[26px] leading-tight text-ink">{s.title}</h3>
                <p className="mt-2 max-w-[19rem] text-[15px] leading-relaxed text-ink-2">{s.body}</p>
              </motion.li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ live agent demo
const LOG: { t: string; text: string; tone?: "ok" | "amber" | "dim" }[] = [
  { t: "12:04:12", text: "Starting scheduled check…" },
  { t: "12:04:13", text: "Fetching https://ssc.gov.in/notices" },
  { t: "12:04:14", text: "304 Not Modified on 1 of 2 sources", tone: "dim" },
  { t: "12:04:15", text: "Comparing with last snapshot…" },
  { t: "12:04:15", text: "3 lines changed: 'CGL 2026 Tier-I Result'", tone: "amber" },
  { t: "12:04:16", text: "Rules: contains 'result' + 'CGL 2026' ✓" },
  { t: "12:04:18", text: "AI judge: condition met (confidence 0.94)", tone: "ok" },
  { t: "12:04:18", text: "Evidence quote verified on page ✓", tone: "ok" },
  { t: "12:04:21", text: "Follow-up: extracted 2 deadlines, 3 links" },
  { t: "12:04:22", text: "Alert sent · Telegram · Email", tone: "amber" },
  { t: "12:04:22", text: "Next check in 2 hours." },
];

const TIMELINE = ["idle", "ok", "idle", "idle", "ok", "amber", "idle", "idle", "ok", "idle", "idle", "err", "idle", "ok", "idle", "amber", "idle", "ok"];

export function LiveDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-100px" });
  const reduce = useReducedMotion();
  const [n, setN] = useState(reduce ? LOG.length : 0);
  useEffect(() => {
    if (!inView || reduce) return;
    const t = setInterval(() => setN((x) => (x >= LOG.length + 6 ? 0 : x + 1)), 650);
    return () => clearInterval(t);
  }, [inView, reduce]);
  const shown = LOG.slice(0, Math.min(n, LOG.length));

  return (
    <section aria-labelledby="live-title" className="defer-paint relative border-y border-line bg-elevated/40 py-24 sm:py-28">
      <div className="mx-auto grid max-w-[1440px] gap-14 px-4 sm:px-8 lg:grid-cols-[1fr_1.15fr] lg:items-center lg:px-12">
        <Reveal>
          <SectionLabel index={3}>The live view</SectionLabel>
          <h2 id="live-title" className="mt-6 font-display text-[clamp(2.4rem,5vw,4.4rem)] leading-[0.95] text-ink">
            Watch the agent <em className="accent">think.</em>
          </h2>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-ink-2">
            Every check streams to your screen in real time: what was fetched, what changed, whether a rule or the AI
            decided, and why. No black boxes, and no AI spend when nothing moved.
          </p>
          <ul className="mt-8 space-y-3 text-[15px] text-ink-2">
            {[
              "Unchanged pages are skipped before any AI call",
              "Simple conditions are decided by deterministic rules",
              "Every alert quotes its evidence, verified on the page",
              "Your 👍/👎 feedback tunes the watch over time",
            ].map((x) => (
              <li key={x} className="flex gap-3">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
                {x}
              </li>
            ))}
          </ul>
        </Reveal>

        <div ref={ref} className="ticked border border-line-strong bg-bg p-4 shadow-float sm:p-6">
          <div className="flex items-center justify-between">
            <SectionLabel index="02">Live activity log</SectionLabel>
            <span className="label-mono flex items-center gap-2 text-ink-2">
              <span className="h-2 w-2 animate-blink rounded-full bg-ok-dot" /> Running
            </span>
          </div>
          <div className="mt-5 flex items-center gap-1.5 overflow-hidden" aria-label="Check timeline" role="img">
            {TIMELINE.map((t, k) => (
              <span key={k} className="flex flex-1 items-center gap-1.5">
                <span
                  className={cn(
                    "h-2.5 w-2.5 shrink-0 rounded-full",
                    t === "idle" && "bg-line-strong",
                    t === "ok" && "bg-ok-dot",
                    t === "amber" && "h-3.5 w-3.5 bg-amber",
                    t === "err" && "bg-err-dot",
                  )}
                />
                {k < TIMELINE.length - 1 && <span className="h-px flex-1 bg-line" />}
              </span>
            ))}
          </div>
          <div
            className="mono-tight mt-5 h-[318px] overflow-hidden border border-line bg-sunken/60 p-4 text-[12.5px] leading-[1.95]"
            aria-live="off"
          >
            {shown.map((l, k) => (
              <motion.div key={k} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.25 }} className="flex gap-4">
                <span className="text-ink-3">{l.t}</span>
                <span className={cn(l.tone === "ok" && "text-ok", l.tone === "amber" && "text-amber-ink", l.tone === "dim" ? "text-ink-3" : !l.tone && "text-ink")}>
                  {l.text}
                </span>
              </motion.div>
            ))}
            {n < LOG.length && <span className="inline-block h-4 w-2 animate-blink bg-ink align-middle" />}
          </div>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ alert preview
export function AlertPreview() {
  const [state, setState] = useState<"idle" | "approved" | "dismissed">("idle");
  return (
    <section aria-labelledby="alert-title" className="defer-paint relative overflow-hidden py-24 sm:py-32">
      <Topo />
      <div className="relative mx-auto grid max-w-[1440px] gap-16 px-4 sm:px-8 lg:grid-cols-[1fr_1.1fr] lg:items-center lg:px-12">
        <Reveal>
          <SectionLabel index={5}>What an alert looks like</SectionLabel>
          <h2 id="alert-title" className="mt-6 font-display text-[clamp(2.6rem,5.6vw,5rem)] leading-[0.95] text-ink">
            It doesn&apos;t just ping.
            <br />
            <span className="text-accent-display">
              It <em>finishes the job.</em>
            </span>
          </h2>
          <p className="mt-7 max-w-lg text-lg leading-relaxed text-ink-2">
            Watchtower doesn&apos;t just tell you something changed. It reads the page, extracts what matters, and
            delivers a clear, actionable alert. Follow-ups like calendar entries wait for your one-tap approval.
          </p>
          <div className="mt-10 hidden items-end gap-5 lg:flex">
            <CategoryArt slug="other" seed="alert-art" className="h-28 w-40 border border-line grayscale" />
            <div className="label-mono border-l border-line pl-4 text-[10px] leading-[1.9] text-ink-3">
              Turn
              <br />
              changes
              <br />
              into
              <br />
              action →
            </div>
          </div>
        </Reveal>

        <div className="relative">
          <Reveal y={30}>
            <article className="ticked relative border border-line-strong bg-elevated p-5 shadow-float sm:p-7" aria-label="Example alert">
              <span className="absolute inset-y-6 left-0 w-[3px] bg-amber" aria-hidden />
              <div className="flex items-center justify-between gap-3">
                <span className="label-mono flex items-center gap-2 text-ink">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-amber text-on-amber">★</span>
                  New opportunity detected
                </span>
                <span className="text-sm text-ink-3">2h ago</span>
              </div>
              <h3 className="mt-4 font-display text-[28px] leading-tight text-ink">IIT Delhi Summer Research Internship</h3>
              <p className="mt-2 text-[15px] text-ink-2">A new research internship has been announced for Summer 2027.</p>
              <dl className="mt-5 divide-y divide-line border border-line bg-bg/60">
                {[
                  { icon: Calendar, k: "Application deadline", v: "15 Apr 2027" },
                  { icon: CreditCard, k: "Application fee", v: "₹0 (free)" },
                  { icon: Link2, k: "Apply at", v: "iitd.ac.in/internships", link: true },
                ].map((r) => (
                  <div key={r.k} className="flex items-center gap-3 px-4 py-3 text-[14.5px]">
                    <r.icon className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                    <dt className="w-40 shrink-0 text-ink-2 sm:w-48">{r.k}</dt>
                    <dd className={cn("min-w-0 truncate font-medium", r.link ? "text-info underline underline-offset-4" : "text-ink")}>{r.v}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-4 flex items-center gap-3 border border-line bg-bg/60 px-4 py-3 text-[13px] text-ink-2">
                <ExternalLink className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                <span className="min-w-0 truncate">Source · iitd.ac.in/news/summer-research-internship-2027</span>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3">
                {state === "idle" ? (
                  <>
                    <Button onClick={() => setState("approved")} size="lg">
                      Add to calendar <ArrowRight className="h-4 w-4" />
                    </Button>
                    <Button onClick={() => setState("dismissed")} size="lg" variant="outline">
                      Dismiss
                    </Button>
                  </>
                ) : (
                  <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="col-span-2 flex h-12 items-center justify-between border border-line px-4 text-sm text-ink-2" role="status">
                    {state === "approved" ? "✓ Approved: calendar invite created (demo)" : "Dismissed. The watch learns from this (demo)."}
                    <button className="text-ink underline underline-offset-4" onClick={() => setState("idle")}>
                      Reset
                    </button>
                  </motion.p>
                )}
              </div>
            </article>
          </Reveal>

          <div className="mt-8 grid grid-cols-3 gap-3 lg:absolute lg:-right-6 lg:top-6 lg:mt-0 lg:flex lg:w-auto lg:translate-x-full lg:flex-col lg:gap-10 xl:translate-x-[105%]">
            {[
              { icon: Mail, label: "Delivered to email" },
              { icon: Send, label: "Delivered to Telegram" },
              { icon: Smartphone, label: "Pushed to your phone" },
            ].map((c, k) => (
              <Reveal key={c.label} delay={0.2 + k * 0.12} className="flex flex-col items-center gap-2 lg:flex-row lg:gap-4">
                <span className="grid h-14 w-14 place-items-center rounded-full border border-line-strong bg-bg lg:h-16 lg:w-16">
                  <c.icon className="h-6 w-6 text-ink" strokeWidth={1.4} aria-hidden />
                </span>
                <span className="label-mono text-center text-[10px] text-ink-3 lg:hidden xl:inline">{c.label}</span>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ closing call to action
export function ClosingCta({ signedInHref }: { signedInHref?: string }) {
  return (
    <section aria-labelledby="cta-title" className="defer-paint relative overflow-hidden border-t border-line">
      <div className="absolute inset-x-0 bottom-0 h-[78%]">
        <ObservatoryScene />
      </div>
      <div className="relative mx-auto max-w-[1440px] px-4 pb-[min(52vw,420px)] pt-24 text-center sm:px-8 lg:px-12">
        <Crosshair className="mx-auto mb-6" size={40} />
        <h2 id="cta-title" className="mx-auto max-w-4xl font-display text-[clamp(2.6rem,6vw,5.4rem)] leading-[0.95] text-ink">
          A quieter internet for a more <em className="accent">informed you.</em>
        </h2>
        <p className="mx-auto mt-6 max-w-xl text-lg text-ink-2">Start free. Five watches, every channel, no card needed.</p>
        <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
          <Button asChild size="lg" variant="amber" mono>
            <Link href={signedInHref || "/signup"}>
              Start watching <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline" mono>
            <Link href="/pricing">Compare plans</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ FAQ
const FAQ = [
  {
    q: "What can Watchtower watch?",
    a: "Any public web page, RSS/Atom feed or JSON endpoint: exam and result notices, company careers pages, product prices and stock, scholarship portals, release notes, government circulars. It can't log in to your accounts or read private data.",
  },
  {
    q: "How is this different from a page-change alert?",
    a: "Page monitors tell you that something changed. Watchtower decides whether the change is the thing you asked about, quotes the evidence, extracts deadlines and links, and stays quiet otherwise. Unchanged pages and cosmetic edits never reach the AI.",
  },
  {
    q: "What are community watches?",
    a: "Public watches anyone can subscribe to, like 'UPSC notifications' or 'SDE openings at Indian startups'. One check serves every subscriber, which is why subscriptions are generous on every plan.",
  },
  {
    q: "Which alert channels are supported?",
    a: "Email, browser push notifications and Telegram on every plan, with instant or daily-digest delivery and quiet hours. Pro adds signed webhooks and an API.",
  },
  {
    q: "Do I need a credit card?",
    a: "No. The free plan includes five watches and 25 community subscriptions. Paid plans add faster checks, more watches and self-tuning.",
  },
];

export function Faq() {
  return (
    <section aria-labelledby="faq-title" className="defer-paint mx-auto max-w-[1100px] px-4 py-24 sm:px-8">
      <SectionLabel index={7}>Questions</SectionLabel>
      <h2 id="faq-title" className="mt-6 font-display text-[clamp(2.2rem,4.6vw,3.8rem)] leading-none text-ink">
        Good to <em className="accent">know.</em>
      </h2>
      <div className="mt-10 divide-y divide-line border-y border-line">
        {FAQ.map((f) => (
          <details key={f.q} className="group py-5 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-6 text-left text-lg font-medium text-ink">
              {f.q}
              <span className="grid h-8 w-8 shrink-0 place-items-center border border-line-strong text-ink-2 transition-transform duration-300 group-open:rotate-45" aria-hidden>
                +
              </span>
            </summary>
            <p className="mt-3 max-w-3xl text-[15.5px] leading-relaxed text-ink-2">{f.a}</p>
          </details>
        ))}
      </div>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: FAQ.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })),
          }),
        }}
      />
    </section>
  );
}

