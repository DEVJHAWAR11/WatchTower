import type { Metadata } from "next";
import { Suspense } from "react";

import { AdminConsole } from "@/components/app/admin";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Admin" };

export default function Page() {
  return (
    <Suspense fallback={<PageLoader />}>
      <AdminConsole />
    </Suspense>
  );
}
