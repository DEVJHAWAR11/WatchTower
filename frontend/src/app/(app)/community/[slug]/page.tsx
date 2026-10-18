import type { Metadata } from "next";
import { Suspense } from "react";

import { CommunityWatchRoute } from "@/components/app/community";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Community watch" };

export default function Page({ params }: { params: Promise<{ slug: string }> }) {
  return (
    <Suspense fallback={<PageLoader />}>
      <CommunityWatchRoute params={params} />
    </Suspense>
  );
}
