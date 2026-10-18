import type { Metadata } from "next";
import { Suspense } from "react";

import { IntakeFlow } from "@/components/app/intake-flow";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "New watch" };

export default function NewWatchPage() {
  return (
    <Suspense fallback={<PageLoader />}>
      <IntakeFlow />
    </Suspense>
  );
}
