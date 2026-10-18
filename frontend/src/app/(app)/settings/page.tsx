import type { Metadata } from "next";
import { Suspense } from "react";

import { SettingsPage } from "@/components/app/settings";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return (
    <Suspense fallback={<PageLoader />}>
      <SettingsPage />
    </Suspense>
  );
}
