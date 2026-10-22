import type { Metadata } from "next";
import { Suspense } from "react";

import { Topo } from "@/components/art/topo";
import { ExploreBrowser } from "@/components/community/explore-browser";
import { WatchCardSkeleton } from "@/components/community/watch-card";
import { Kicker, SectionLabel } from "@/components/ui/display";
import { getCategories, getExplore } from "@/lib/server/public-api";

export const metadata: Metadata = {
  title: "Community watches: exams, jobs, scholarships and deals",
  description:
    "Subscribe to public watches the community keeps on SSC, UPSC and NTA notices, company job openings, scholarships, IPOs and price drops. Free alerts by email, push or Telegram.",
  alternates: { canonical: "/explore" },
};

export default function ExplorePage() {
  return (
    <div className="relative">
      <Topo className="h-[520px]" />
      <div className="relative mx-auto max-w-[1440px] px-4 pb-24 pt-12 sm:px-8 lg:px-12">
        <div className="flex items-start justify-between gap-8">
          <div>
            <SectionLabel>/ Community</SectionLabel>
            <h1 className="mt-6 font-display text-[clamp(2.8rem,6vw,5.2rem)] leading-[0.95] text-ink">
              Watches for a more
              <br />
              informed <em className="accent">you.</em>
            </h1>
            <p className="mt-5 max-w-xl text-lg text-ink-2">
              Explore watches created by the community. Subscribe in one tap, fork one to customise it, or publish your own.
            </p>
          </div>
          <Kicker className="hidden pt-4 lg:block" lines={["Same web.", "More signals.", "A more", "informed you."]} />
        </div>
        <div className="mt-10">
          <Suspense fallback={<GridFallback />}>
            <ExploreData />
          </Suspense>
        </div>
      </div>
    </div>
  );
}

async function ExploreData() {
  const [initial, categories] = await Promise.all([getExplore("trending", "", "", 24), getCategories()]);
  return <ExploreBrowser initial={initial} initialCategories={categories} />;
}

function GridFallback() {
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 8 }, (_, i) => (
        <WatchCardSkeleton key={i} />
      ))}
    </div>
  );
}
