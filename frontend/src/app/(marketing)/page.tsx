import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { CategoryIcon } from "@/components/art/category";
import { Topo } from "@/components/art/topo";
import { WatchCard, WatchCardSkeleton } from "@/components/community/watch-card";
import { Hero } from "@/components/marketing/hero";
import { Pricing } from "@/components/marketing/pricing";
import { AlertPreview, ClosingCta, Faq, HowItWorks, LiveDemo, Reveal, StatsStrip } from "@/components/marketing/sections";
import { Button } from "@/components/ui/button";
import { Coordinates, SectionLabel } from "@/components/ui/display";
import { getCategories, getExplore, getPlans } from "@/lib/server/public-api";

export default function Home() {
  return (
    <>
      <Hero />
      <StatsStrip />
      <HowItWorks />
      <LiveDemo />
      <CommunitySection />
      <AlertPreview />
      <section id="pricing" aria-labelledby="pricing-title" className="defer-paint relative scroll-mt-20 border-t border-line py-24 sm:py-32">
        <div className="mx-auto max-w-[1240px] px-4 sm:px-8">
          <Reveal className="text-center">
            <SectionLabel index={6} className="items-center">Pricing</SectionLabel>
            <h2 id="pricing-title" className="mt-6 font-display text-[clamp(2.6rem,5.6vw,5rem)] leading-[0.95] text-ink">
              Priced like a <em className="accent">cup of chai.</em>
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-lg text-ink-2">
              Shared community checks keep costs tiny, so plans stay cheap. Start free; upgrade when you watch more.
            </p>
          </Reveal>
          <div className="mt-12">
            <Suspense fallback={<div className="h-[560px]" />}>
              <PlansBlock />
            </Suspense>
          </div>
        </div>
      </section>
      <Faq />
      <ClosingCta />
    </>
  );
}

async function PlansBlock() {
  const plans = await getPlans();
  return <Pricing plans={plans} />;
}

function CommunitySection() {
  return (
    <section aria-labelledby="community-title" className="defer-paint relative overflow-hidden border-t border-line py-24 sm:py-32">
      <Topo />
      <div className="relative mx-auto max-w-[1440px] px-4 sm:px-8 lg:px-12">
        <div className="grid gap-8 lg:grid-cols-[1.5fr_1fr] lg:items-end">
          <Reveal>
            <SectionLabel index={4}>Community watches</SectionLabel>
            <h2 id="community-title" className="mt-6 font-display text-[clamp(2.6rem,5.6vw,5rem)] leading-[0.95] text-ink">
              Watched <em className="accent">together.</em>
            </h2>
            <p className="mt-5 max-w-xl text-lg text-ink-2">
              Subscribe to public watches for exams, jobs, scholarships and deals. One check serves everyone, so it
              costs you nothing extra.
            </p>
          </Reveal>
          <Reveal delay={0.1} className="flex items-end justify-between gap-6 lg:justify-end">
            <Button asChild variant="outline" size="lg" mono>
              <Link href="/explore">
                Browse all watches <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <Coordinates className="hidden xl:block" />
          </Reveal>
        </div>
        <Suspense
          fallback={
            <div className="mt-12 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 8 }, (_, i) => (
                <WatchCardSkeleton key={i} />
              ))}
            </div>
          }
        >
          <CommunityGrid />
        </Suspense>
      </div>
    </section>
  );
}

async function CommunityGrid() {
  const [page, cats] = await Promise.all([getExplore("trending", "", "", 8), getCategories()]);
  const items = page?.items ?? [];
  if (items.length >= 3) {
    return (
      <div className="mt-12 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((w, i) => (
          <Reveal key={w.id} delay={(i % 4) * 0.06}>
            <WatchCard watch={w} trending={i === 1} />
          </Reveal>
        ))}
      </div>
    );
  }
  // Young catalogue: show the categories people can browse and publish into.
  const list = (cats ?? []).filter((c) => c.slug !== "other").slice(0, 8);
  return (
    <div className="mt-12">
      <div className="grid gap-px border border-line bg-line sm:grid-cols-2 xl:grid-cols-4">
        {list.map((c) => (
          <Link key={c.slug} href={`/explore?category=${c.slug}`} className="group flex flex-col gap-3 bg-bg p-6 transition-colors hover:bg-elevated">
            <CategoryIcon slug={c.slug} className="h-6 w-6 text-ink" />
            <span className="font-display text-[24px] leading-tight text-ink">{c.name}</span>
            <span className="text-[14px] text-ink-2">{c.description}</span>
            <span className="label-mono mt-auto flex items-center gap-2 pt-2 text-ink-3 group-hover:text-ink">
              {c.watch_count ? `${c.watch_count} watches` : "Be the first to publish"} <ArrowRight className="h-3.5 w-3.5" />
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
