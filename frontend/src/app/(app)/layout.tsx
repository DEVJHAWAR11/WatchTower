import type { Metadata } from "next";
import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { robots: { index: false, follow: false } };

/** The signed-in app is per-user and rendered at request time; the fallback is the static shell. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="min-h-dvh lg:grid lg:grid-cols-[260px_minmax(0,1fr)]">
          <div className="hidden border-r border-line lg:block" />
          <PageLoader />
        </div>
      }
    >
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
