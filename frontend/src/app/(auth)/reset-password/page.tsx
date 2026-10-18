import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { ResetForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Choose a new password", robots: { index: false } };

export default function ResetPage() {
  return (
    <AuthShell index="05" kicker="Account recovery" title="Choose a" accent="new password." intro="Pick something you haven't used elsewhere.">
      <ResetForm />
    </AuthShell>
  );
}
