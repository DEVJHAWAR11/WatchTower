"use client";

import { ArrowRight, BarChart3, Building2, FileText, Globe2, Rss, Send } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { CategoryArt } from "@/components/art/category";
import { ObservatoryScene } from "@/components/art/observatory";
import { Radar } from "@/components/art/radar";
import { Topo } from "@/components/art/topo";
import { Button } from "@/components/ui/button";
import { Coordinates, Crosshair, Kicker, SectionLabel } from "@/components/ui/display";
import { useSignedIn } from "@/lib/use-session";

import { SystemStatus } from "./system-status";

const SCENARIOS = [
  {
    host: "ssc.gov.in",
    path: "/notices",
    found: "SSC CGL 2026 Tier-I result declared. Merit list PDF published.",
    tags: ["Exams", "Result", "Official"],
  },
  {
    host: "careers.razorpay.com",
    path: "/jobs",
    found: "New role: SDE-1 Backend, Bengaluru. Applications open till 30 Oct.",
    tags: ["Jobs", "Backend", "Bengaluru"],
  },
  {
    host: "scholarships.gov.in",
    path: "/",
    found: "NSP 2026-27 portal open. Post-matric deadline: 15 Nov.",
    tags: ["Scholarship", "Deadline", "NSP"],
  },
];

const SOURCES = [
  { icon: Globe2, title: "Websites", body: "Notices, news, any URL" },
  { icon: Rss, title: "Feeds", body: "RSS, Atom and JSON" },
  { icon: Building2, title: "Careers pages", body: "Company & ATS boards" },
  { icon: FileText, title: "Govt & exams", body: "SSC, UPSC, NTA, boards" },
];

const ease = [0.2, 0.8, 0.2, 1] as const;

export function Hero() {
  const signedIn = useSignedIn();
  const reduce = useReducedMotion();
  const [i, setI] = useState(0);
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const radarY = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [0, 90]);
  const radarRotate = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [0, 12]);
  const textY = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [0, -40]);

  useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setI((x) => (x + 1) % SCENARIOS.length), 5200);
    return () => clearInterval(t);
  }, [reduce]);
  const s = SCENARIOS[i];

  return (
    <section ref={ref} className="relative overflow-hidden" aria-labelledby="hero-title">
      <Topo className="opacity-80" />
      <div className="relative mx-auto grid max-w-[1440px] gap-6 px-4 pb-10 pt-8 sm:px-8 lg:grid-cols-[minmax(0,1.06fr)_minmax(0,1fr)] lg:gap-4 lg:px-12 lg:pb-0 lg:pt-14">
        {/* copy */}
        <motion.div style={{ y: textY }} className="relative z-10 flex flex-col">
          <div className="flex items-start gap-10">
            <SectionLabel index={1}>
              Always on
              <br />
              across the web
            </SectionLabel>
            <Crosshair className="-mt-1 hidden sm:block" size={56} />
          </div>
          <motion.h1
            id="hero-title"
            className="mt-8 font-display text-[clamp(3rem,6.3vw,6.6rem)] leading-[0.92] text-ink"
            initial={{ y: 18 }}
            animate={{ y: 0 }}
            transition={{ duration: 0.9, ease }}
          >
            The web moves.
            <br />
            We <em className="accent">keep watch.</em>
          </motion.h1>
          <motion.p
            className="mt-7 max-w-xl text-[clamp(1.05rem,1.5vw,1.3rem)] leading-relaxed text-ink-2"
            initial={{ y: 12 }}
            animate={{ y: 0 }}
            transition={{ duration: 0.8, delay: 0.15, ease }}
          >
            Describe what you care about in plain English. AI agents watch the sources that matter, judge what really
            changed, and bring you the signal, before you have to look.
          </motion.p>
          <motion.div
            className="mt-9 flex flex-col gap-3 sm:flex-row"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.28, ease }}
          >
            <Button asChild size="lg" mono className="group">
              <Link href={signedIn ? "/watches/new" : "/signup"}>
                Deploy your first watch
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline" mono>
              <Link href="/explore">Explore community watches</Link>
            </Button>
          </motion.div>
          <SystemStatus className="mt-8" />

          <div className="mt-12 hidden lg:block">
            <div className="label-mono mb-4 text-ink-3">[ Watch any source ]</div>
            <ul className="grid grid-cols-4 divide-x divide-line border-y border-line">
              {SOURCES.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex gap-3 px-4 py-4 first:pl-0">
                  <Icon className="mt-0.5 h-5 w-5 shrink-0 text-ink" strokeWidth={1.4} aria-hidden />
                  <div>
                    <div className="text-sm font-medium text-ink">{title}</div>
                    <div className="text-[13px] leading-snug text-ink-3">{body}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </motion.div>

        {/* instrument */}
        <div className="relative h-[460px] sm:h-[600px] lg:h-[760px]" aria-hidden={false}>
          <div className="absolute left-0 top-4 hidden w-[70px] flex-col gap-2 xl:flex">
            <div className="label-mono mb-2 text-[9.5px] leading-tight text-ink-3">From noise<br />to signal</div>
            {["jobs", "government", "ipo", "scholarships", "news"].map((c, k) => (
              <motion.div key={c} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.4 + k * 0.08 }}>
                <CategoryArt slug={c} seed={`hero-${c}`} className="h-[70px] w-[70px] border border-line opacity-80 grayscale" />
              </motion.div>
            ))}
            <Kicker className="mt-3" lines={["// monitor", "// analyze", "// alert"]} />
          </div>

          <motion.div style={{ y: radarY, rotate: radarRotate }} className="absolute right-[-8%] top-0 aspect-square w-[108%] sm:right-[2%] sm:w-[92%] lg:right-[-2%] lg:w-[88%]">
            <motion.div initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1.2, ease }} className="h-full w-full">
              <Radar />
            </motion.div>
          </motion.div>

          <div className="pointer-events-none absolute bottom-0 right-[-4%] h-[62%] w-[96%] [mask-image:linear-gradient(to_right,transparent,black_22%,black_88%,transparent),linear-gradient(to_bottom,transparent,black_30%)] [mask-composite:intersect] sm:right-0 sm:w-[82%]">
            <ObservatoryScene />
          </div>

          <div className="absolute right-2 top-2 hidden text-right sm:block">
            <div className="label-mono text-[10px] text-ink-3">Global coverage<br />Real-time monitoring</div>
            <Coordinates className="mt-16" />
          </div>

          {/* floating readouts */}
          <div className="absolute left-[2%] top-[14%] w-[min(270px,62%)] sm:left-[14%] xl:left-[17%]" role="status" aria-live="polite">
            <AnimatePresence mode="wait">
              <motion.div
                key={`src-${i}`}
                initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -8, filter: "blur(4px)" }}
                transition={{ duration: 0.45, ease }}
                className="ticked border border-line bg-elevated/95 p-3.5 shadow-card backdrop-blur"
              >
                <div className="flex items-start gap-3">
                  <FileText className="mt-0.5 h-5 w-5 text-ink" strokeWidth={1.4} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="label-mono text-[10px] text-ink">Source checked</div>
                    <div className="mono-tight truncate text-[12px] text-ink-2">{s.host}{s.path}</div>
                    <div className="mono-tight mt-1 text-[10.5px] text-ink-3">every 2h · 0 AI calls if unchanged</div>
                  </div>
                  <span className="mt-1 h-2 w-2 rounded-full bg-ok-dot" />
                </div>
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="absolute right-[1%] top-[40%] w-[min(290px,70%)] sm:right-[3%]">
            <AnimatePresence mode="wait">
              <motion.div
                key={`chg-${i}`}
                initial={{ opacity: 0, x: 14 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                transition={{ duration: 0.5, delay: 0.25, ease }}
                className="ticked border border-line bg-elevated/95 p-3.5 shadow-card backdrop-blur"
              >
                <div className="flex items-center gap-2.5">
                  <span className="relative grid h-4 w-4 place-items-center">
                    <span className="absolute inset-0 animate-ping-slow rounded-full bg-amber" />
                    <span className="relative h-3 w-3 rounded-full bg-amber" />
                  </span>
                  <span className="label-mono text-[10px] text-ink">Change found</span>
                </div>
                <p className="mono-tight mt-2 text-[12px] leading-relaxed text-ink-2">{s.found}</p>
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="absolute right-[3%] top-[62%] hidden w-[230px] sm:block">
            <AnimatePresence mode="wait">
              <motion.div
                key={`sig-${i}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.45, delay: 0.5, ease }}
                className="border border-line bg-elevated/95 p-3 shadow-card backdrop-blur"
              >
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-amber-ink" aria-hidden />
                  <span className="label-mono text-[10px] text-amber-ink">High signal</span>
                  <Send className="ml-auto h-3.5 w-3.5 text-ink-3" aria-hidden />
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {s.tags.map((t) => (
                    <span key={t} className="mono-tight border border-line-strong/70 px-1.5 py-0.5 text-[10px] uppercase text-ink-2">
                      {t}
                    </span>
                  ))}
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}
