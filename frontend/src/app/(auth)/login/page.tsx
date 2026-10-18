import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Sign in", alternates: { canonical: "/login" } };

export default function LoginPage() {
  return (
    <AuthShell index="05" kicker="Welcome back" title="Pick up" accent="where you left off." intro="Sign in to see what your watches found while you were away.">
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
