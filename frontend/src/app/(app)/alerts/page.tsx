import type { Metadata } from "next";
import { Suspense } from "react";

import { AlertsInbox } from "@/components/app/alerts-inbox";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Alerts" };

export default function AlertsPage() {
  return (
    <Suspense fallback={<PageLoader />}>
      <AlertsInbox />
    </Suspense>
  );
}
