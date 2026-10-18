import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthCallback } from "@/components/auth/callback";
import { PageLoader } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Signing you in", robots: { index: false } };

export default function CallbackPage() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center">
      <Suspense fallback={<PageLoader label="Signing you in" />}>
        <AuthCallback />
      </Suspense>
    </main>
  );
}
