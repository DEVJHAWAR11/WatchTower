"use client";

import { ArrowRight, Check, Minus } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { Plan } from "@/lib/types";
import { useSignedIn } from "@/lib/use-session";
import { cn, formatInterval } from "@/lib/utils";

/** Mirrors the seeded plans; used only if the API can't be reached while rendering. */
export const FALLBACK_PLANS: Plan[] = [
  {
    id: "free", name: "Free", price_usd_month: 0, price_usd_year: 0,
    limits: { max_watches: 5, max_subscriptions: 25, min_interval_seconds: 21600, acts_per_month: 20, intake_per_day: 10, run_now_per_day: 3, llm_tokens_per_day: 150000, retention_days: 30, max_sources_per_watch: 2, max_alerts_per_hour: 6 },
    features: { channels: ["email", "push", "telegram"], auto_tune: false, js_render: false, api_tokens: false, webhooks: false, per_watch_channels: false, public_watches: true },
  },
  {
    id: "plus", name: "Plus", price_usd_month: 2, price_usd_year: 20,
    limits: { max_watches: 30, max_subscriptions: 150, min_interval_seconds: 3600, acts_per_month: 200, intake_per_day: 40, run_now_per_day: 20, llm_tokens_per_day: 1000000, retention_days: 180, max_sources_per_watch: 3, max_alerts_per_hour: 20 },
    features: { channels: ["email", "push", "telegram"], auto_tune: true, js_render: true, api_tokens: false, webhooks: false, per_watch_channels: true, public_watches: true },
  },
  {
    id: "pro", name: "Pro", price_usd_month: 6, price_usd_year: 60,
    limits: { max_watches: 150, max_subscriptions: 1000, min_interval_seconds: 900, acts_per_month: 1500, intake_per_day: 100, run_now_per_day: 100, llm_tokens_per_day: 5000000, retention_days: 730, max_sources_per_watch: 5, max_alerts_per_hour: 60 },
    features: { channels: ["email", "push", "telegram", "webhook"], auto_tune: true, js_render: true, api_tokens: true, webhooks: true, per_watch_channels: true, public_watches: true },
  },
];

const TAGLINES: Record<string, string> = {
  free: "For trying it out and a few things that matter.",
  plus: "For students and job seekers who track a lot.",
  pro: "For power users, teams and builders.",
};

function retention(days: number) {
  return days >= 365 ? `${Math.round(days / 365)} years` : `${days} days`;
}

function highlights(p: Plan): string[] {
  const l = p.limits;
  return [
    `${l.max_watches} watches of your own`,
    l.max_subscriptions >= 1000 ? "Unlimited community subscriptions*" : `${l.max_subscriptions} community subscriptions`,
    `${formatInterval(l.min_interval_seconds).replace("Every", "Checks as often as every")}`,
    `${l.acts_per_month.toLocaleString("en-IN")} follow-up actions a month`,
    `${l.max_sources_per_watch} sources per watch`,
    `${retention(l.retention_days)} of history`,
  ];
}

const FEATURE_ROWS: { key: string; label: string; get: (p: Plan) => string | boolean }[] = [
  { key: "watches", label: "Own watches", get: (p) => String(p.limits.max_watches) },
  { key: "subs", label: "Community subscriptions", get: (p) => (p.limits.max_subscriptions >= 1000 ? "Unlimited*" : String(p.limits.max_subscriptions)) },
  { key: "interval", label: "Fastest check interval", get: (p) => formatInterval(p.limits.min_interval_seconds).replace("Every ", "") },
  { key: "sources", label: "Sources per watch", get: (p) => String(p.limits.max_sources_per_watch) },
  { key: "acts", label: "Follow-up actions / month", get: (p) => p.limits.acts_per_month.toLocaleString("en-IN") },
  { key: "runnow", label: "Manual checks / day", get: (p) => String(p.limits.run_now_per_day) },
  { key: "alerts", label: "Alerts per hour (cap)", get: (p) => String(p.limits.max_alerts_per_hour) },
  { key: "history", label: "History retention", get: (p) => retention(p.limits.retention_days) },
  { key: "channels", label: "Email, push & Telegram", get: () => true },
  { key: "tune", label: "Auto-tuning from feedback", get: (p) => Boolean(p.features.auto_tune) },
  { key: "render", label: "JavaScript-heavy pages", get: (p) => Boolean(p.features.js_render) },
  { key: "perwatch", label: "Per-watch channels", get: (p) => Boolean(p.features.per_watch_channels) },
  { key: "webhooks", label: "Signed webhooks", get: (p) => Boolean(p.features.webhooks) },
  { key: "api", label: "API tokens", get: (p) => Boolean(p.features.api_tokens) },
];

export function Pricing({ plans, showTable = false, currentPlan }: { plans: Plan[] | null; showTable?: boolean; currentPlan?: string }) {
  const list = plans && plans.length ? plans : FALLBACK_PLANS;
  const [yearly, setYearly] = useState(false);
  const signedIn = useSignedIn();

  return (
    <div>
      <div className="flex justify-center">
        <div role="radiogroup" aria-label="Billing period" className="inline-flex border border-line-strong p-1">
          {[
            { v: false, label: "Monthly" },
            { v: true, label: "Yearly · 2 months free" },
          ].map((o) => (
            <button
              key={o.label}
              role="radio"
              aria-checked={yearly === o.v}
              onClick={() => setYearly(o.v)}
              className={cn("label-mono px-4 py-2 transition-colors", yearly === o.v ? "bg-ink text-bg" : "text-ink-2 hover:text-ink")}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-12 grid gap-5 lg:grid-cols-3">
        {list.map((p, k) => {
          const featured = p.id === "plus";
          const price = yearly ? p.price_usd_year : p.price_usd_month;
          const isCurrent = currentPlan === p.id;
          return (
            <motion.article
              key={p.id}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: k * 0.1, ease: [0.2, 0.8, 0.2, 1] }}
              className={cn(
                "ticked relative flex flex-col border p-7 sm:p-8",
                featured ? "border-amber bg-amber-soft/40 shadow-card" : "border-line bg-elevated/60",
              )}
              aria-labelledby={`plan-${p.id}`}
            >
              {featured && <span className="label-mono absolute -top-3 left-7 bg-amber px-2 py-1 text-[10px] text-on-amber">Most popular</span>}
              <h3 id={`plan-${p.id}`} className="font-display text-[34px] leading-none text-ink">
                {p.name}
              </h3>
              <p className="mt-2 min-h-[44px] text-[15px] text-ink-2">{TAGLINES[p.id] || ""}</p>
              <div className="mt-6 flex items-baseline gap-2">
                <span className="font-display text-[56px] leading-none text-ink">${price % 1 ? price.toFixed(2) : price}</span>
                <span className="text-sm text-ink-3">{price === 0 ? "forever" : yearly ? "/ year" : "/ month"}</span>
              </div>
              <ul className="mt-7 space-y-3 text-[15px] text-ink-2">
                {highlights(p).map((h) => (
                  <li key={h} className="flex gap-3">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
                    {h}
                  </li>
                ))}
              </ul>
              <div className="mt-8 pt-2">
                {isCurrent ? (
                  <Button variant="subtle" size="lg" className="w-full" disabled>
                    Your current plan
                  </Button>
                ) : p.id === "free" ? (
                  <Button asChild size="lg" variant="outline" className="w-full" mono>
                    <Link href={signedIn ? "/dashboard" : "/signup"}>{signedIn ? "Go to dashboard" : "Start free"}</Link>
                  </Button>
                ) : (
                  <Button asChild size="lg" variant={featured ? "amber" : "primary"} className="w-full" mono>
                    <Link href={signedIn ? `/settings?tab=plan&upgrade=${p.id}` : `/signup?plan=${p.id}`}>
                      Choose {p.name} <ArrowRight className="h-4 w-4" />
                    </Link>
                  </Button>
                )}
              </div>
            </motion.article>
          );
        })}
      </div>
      <p className="mt-5 text-center text-[13px] text-ink-3">Prices in USD. *Fair use: up to 1,000 subscriptions. Cancel anytime.</p>

      {showTable && (
        <div className="mt-20 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left text-[15px]">
            <caption className="sr-only">Plan comparison</caption>
            <thead>
              <tr className="border-b border-line-strong">
                <th scope="col" className="label-mono py-4 pr-4 font-normal text-ink-3">Compare plans</th>
                {list.map((p) => (
                  <th key={p.id} scope="col" className="py-4 pr-4 font-display text-2xl font-normal text-ink">
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FEATURE_ROWS.map((r) => (
                <tr key={r.key} className="border-b border-line">
                  <th scope="row" className="py-3.5 pr-4 font-normal text-ink-2">{r.label}</th>
                  {list.map((p) => {
                    const v = r.get(p);
                    return (
                      <td key={p.id} className="py-3.5 pr-4 text-ink">
                        {v === true ? <Check className="h-4 w-4 text-ok" aria-label="Included" /> : v === false ? <Minus className="h-4 w-4 text-ink-3" aria-label="Not included" /> : v}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
