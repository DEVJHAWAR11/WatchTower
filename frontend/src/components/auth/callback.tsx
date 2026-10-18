"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/ui/spinner";
import { safeNext } from "@/lib/utils";

/** Finishes Google, magic-link, email-confirmation and recovery redirects, whose tokens arrive in the URL fragment. */
export function AuthCallback() {
  const router = useRouter();
  const sp = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    // Never leave tokens in the address bar or history.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    const err = hash.get("error_description") || sp.get("error_description");
    // The URL fragment is external state read once on mount; reporting it is this effect's purpose.
    /* eslint-disable react-hooks/set-state-in-effect */
    if (err) {
      setError(err.replace(/\+/g, " "));
      return;
    }
    const access = hash.get("access_token");
    if (!access) {
      setError("This sign-in link is incomplete or has already been used.");
      return;
    }
    /* eslint-enable react-hooks/set-state-in-effect */
    const type = hash.get("type");
    const next = type === "recovery" ? "/reset-password" : safeNext(sp.get("next"));
    fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json", "x-wt-csrf": "1" },
      body: JSON.stringify({ access_token: access, refresh_token: hash.get("refresh_token"), expires_in: hash.get("expires_in") }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message || "Sign-in failed.");
        router.replace(next);
        router.refresh();
      })
      .catch((e: Error) => setError(e.message));
  }, [router, sp]);

  if (!error) return <PageLoader label="Signing you in" />;
  return (
    <div className="max-w-md px-4 text-center" role="alert">
      <h1 className="font-display text-4xl text-ink">That link didn&apos;t work</h1>
      <p className="mt-3 text-ink-2">{error}</p>
      <div className="mt-6 flex justify-center gap-3">
        <Button asChild>
          <Link href="/login">Back to sign in</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/signup">Create an account</Link>
        </Button>
      </div>
    </div>
  );
}
