import type { Metadata } from "next";
import { Suspense } from "react";

import { PageLoader } from "@/components/ui/spinner";
import { WatchDetailRoute } from "@/components/watch/watch-detail-route";

export const metadata: Metadata = { title: "Watch" };

export default function WatchPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<PageLoader />}>
      <WatchDetailRoute params={params} />
    </Suspense>
  );
}
