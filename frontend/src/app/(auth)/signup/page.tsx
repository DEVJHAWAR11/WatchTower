import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthShell } from "@/components/auth/auth-shell";
import { SignupForm } from "@/components/auth/forms";

export const metadata: Metadata = {
  title: "Create your account",
  description: "Start watching the web with AI agents. Free for five watches.",
  alternates: { canonical: "/signup" },
};

export default function SignupPage() {
  return (
    <AuthShell index="05" kicker="Create your account" title="Start watching" accent="what matters." intro="Set up your account and let Watchtower keep an eye on the web for you.">
      <Suspense>
        <SignupForm />
      </Suspense>
    </AuthShell>
  );
}
