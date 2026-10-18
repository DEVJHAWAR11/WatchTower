import type { Metadata } from "next";
import { Suspense } from "react";

import { CommunityPage } from "@/components/app/community";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Community" };

export default function Page() {
  return (
    <Suspense fallback={<PageLoader />}>
      <CommunityPage />
    </Suspense>
  );
}
