import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { ForgotForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Reset your password", robots: { index: false } };

export default function ForgotPage() {
  return (
    <AuthShell index="05" kicker="Account recovery" title="Lost the" accent="key to the tower?" intro="Enter your email and we'll send a link to set a new password.">
      <ForgotForm />
    </AuthShell>
  );
}
