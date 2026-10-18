import type { Metadata } from "next";
import { Suspense } from "react";

import { Dashboard } from "@/components/app/dashboard";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Dashboard />
    </Suspense>
  );
}
