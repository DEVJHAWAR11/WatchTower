import type { Metadata } from "next";
import { Suspense } from "react";

import { AlertDetailRoute } from "@/components/app/alerts-inbox";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Alert" };

export default function AlertPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<PageLoader />}>
      <AlertDetailRoute params={params} />
    </Suspense>
  );
}
