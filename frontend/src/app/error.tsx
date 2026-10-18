"use client";

import { RotateCw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { SectionLabel } from "@/components/ui/display";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main id="main" className="grid min-h-[70dvh] place-items-center px-4 py-16">
      <div className="max-w-xl text-center">
        <SectionLabel className="items-center" index="500">Interference</SectionLabel>
        <h1 className="mt-6 font-display text-[clamp(2.4rem,6vw,4.4rem)] leading-[0.95] text-ink">
          Something went <em className="accent">sideways.</em>
        </h1>
        <p className="mt-5 text-lg text-ink-2">An unexpected error interrupted this page. Your watches keep running in the background.</p>
        {error.digest && <p className="label-mono mt-3 normal-case tracking-normal text-ink-3">Ref: {error.digest}</p>}
        <div className="mt-8 flex justify-center gap-3">
          <Button onClick={reset} mono>
            <RotateCw className="h-4 w-4" /> Try again
          </Button>
          <Button asChild variant="outline" mono>
            <Link href="/">Home</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
