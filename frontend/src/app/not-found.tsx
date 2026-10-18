import Link from "next/link";

import { Radar } from "@/components/art/radar";
import { Button } from "@/components/ui/button";
import { SectionLabel } from "@/components/ui/display";

export default function NotFound() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-4 py-16">
      <div className="grid max-w-4xl items-center gap-10 md:grid-cols-[1fr_320px]">
        <div>
          <SectionLabel index="404">Signal lost</SectionLabel>
          <h1 className="mt-6 font-display text-[clamp(2.8rem,7vw,5.4rem)] leading-[0.95] text-ink">
            Nothing on the <em className="accent">radar.</em>
          </h1>
          <p className="mt-5 max-w-md text-lg text-ink-2">
            This page moved, was archived, or never existed. Even we can&apos;t watch what isn&apos;t there.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild mono>
              <Link href="/">Back to home</Link>
            </Button>
            <Button asChild variant="outline" mono>
              <Link href="/explore">Browse community watches</Link>
            </Button>
          </div>
        </div>
        <div className="mx-auto w-64 md:w-full">
          <Radar labels={false} />
        </div>
      </div>
    </main>
  );
}
