import type { Metadata } from "next";
import { Suspense } from "react";

import { Topo } from "@/components/art/topo";
import { Pricing } from "@/components/marketing/pricing";
import { Faq } from "@/components/marketing/sections";
import { SectionLabel } from "@/components/ui/display";
import { getPlans } from "@/lib/server/public-api";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Watchtower is free for five watches. Plus is $2/month and Pro is $6/month, with faster checks, more watches, auto-tuning, webhooks and an API.",
  alternates: { canonical: "/pricing" },
};

export default function PricingPage() {
  return (
    <div className="relative">
      <Topo className="h-[560px]" />
      <div className="relative mx-auto max-w-[1240px] px-4 pb-10 pt-14 sm:px-8">
        <div className="text-center">
          <SectionLabel className="items-center">/ Pricing</SectionLabel>
          <h1 className="mt-6 font-display text-[clamp(2.8rem,6vw,5.4rem)] leading-[0.95] text-ink">
            Simple plans for a <em className="accent">watchful life.</em>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-ink-2">
            Start free. Upgrade when you need faster checks, more watches or the API.
          </p>
        </div>
        <div className="mt-14">
          <Suspense fallback={<div className="h-[640px]" />}>
            <PlansTable />
          </Suspense>
        </div>
      </div>
      <Faq />
    </div>
  );
}

async function PlansTable() {
  const plans = await getPlans();
  return (
    <>
      <h2 className="sr-only">Plans and prices</h2>
      <Pricing plans={plans} showTable />
    </>
  );
}
