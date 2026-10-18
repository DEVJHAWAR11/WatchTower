"use client";

import { ArrowRight, Eye, EyeOff, Mail } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { ApiError, api, errorMessage } from "@/lib/api";
import { safeNext } from "@/lib/utils";

function callbackUrl(next?: string) {
  const u = new URL("/auth/callback", window.location.origin);
  if (next) u.searchParams.set("next", next);
  return u.toString();
}

export function GoogleButton({ next, label = "Continue with Google" }: { next?: string; label?: string }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const r = await api<{ message: string }>("auth/oauth/google", { query: { redirect_to: callbackUrl(next) } });
      if (!r.message?.startsWith("https://")) throw new Error("Google sign-in isn't available right now.");
      window.location.assign(r.message);
    } catch (e) {
      toast.error(errorMessage(e, "Google sign-in isn't available right now."));
      setBusy(false);
    }
  };
  return (
    <Button type="button" variant="subtle" size="lg" className="w-full border-line-strong bg-transparent" onClick={go} loading={busy}>
      <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
        <path fill="#FBBC05" d="M5.84 14.09A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.43.34-2.09V7.07H2.18A11 11 0 0 0 1 12c0 1.78.43 3.45 1.18 4.93l3.66-2.84z" />
        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
      </svg>
      {label}
    </Button>
  );
}

export function OrDivider() {
  return (
    <div className="my-6 flex items-center gap-4 text-sm text-ink-3" role="separator">
      <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
    </div>
  );
}

function PasswordInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={show ? "text" : "password"} className="pr-12" />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center text-ink-3 hover:text-ink"
        aria-label={show ? "Hide password" : "Show password"}
      >
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

function passwordProblem(p: string): string | null {
  if (p.length < 8) return "Use at least 8 characters.";
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^\w\s]/].filter((r) => r.test(p)).length;
  if (classes < 2) return "Mix letters with numbers or symbols.";
  return null;
}

function fieldErrors(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || !Array.isArray(e.details)) return {};
  const out: Record<string, string> = {};
  for (const d of e.details as { loc?: string[]; msg?: string }[]) {
    const k = d.loc?.[d.loc.length - 1];
    if (k && d.msg) out[k] = d.msg.replace(/^Value error, /, "");
  }
  return out;
}

// ------------------------------------------------------------------ sign up
export function SignupForm() {
  const sp = useSearchParams();
  const next = safeNext(sp.get("next"), sp.get("plan") ? `/settings?tab=plan&upgrade=${sp.get("plan")}` : "/watches/new");
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const pw = passwordProblem(password);
    if (pw) return setErrors({ password: pw });
    setErrors({});
    setBusy(true);
    try {
      const r = await api<{ signed_in: boolean; message: string | null }>("auth/signup", {
        body: { email: email.trim(), password, display_name: name.trim() || null, redirect_to: callbackUrl(next) },
      });
      if (r.signed_in) {
        router.replace(next);
        router.refresh();
      } else setSent(true);
    } catch (err) {
      const fe = fieldErrors(err);
      if (Object.keys(fe).length) setErrors(fe);
      else setErrors({ form: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  if (sent) return <CheckInbox email={email} what="confirm your account" />;

  return (
    <div>
      <GoogleButton next={next} />
      <OrDivider />
      <form onSubmit={submit} className="space-y-5" noValidate>
        <Field label="Full name" htmlFor="name" error={errors.display_name}>
          <Input id="name" autoComplete="name" placeholder="Asha Verma" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email}>
          <Input id="email" type="email" autoComplete="email" required placeholder="you@university.edu" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={Boolean(errors.email)} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password} hint="At least 8 characters, mixing letters with numbers or symbols.">
          <PasswordInput id="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={Boolean(errors.password)} />
        </Field>
        {errors.form && (
          <p className="border border-err/30 bg-err-soft px-3 py-2 text-sm text-err" role="alert">
            {errors.form}
          </p>
        )}
        <Button type="submit" size="lg" variant="amber" className="w-full" loading={busy}>
          Create account <ArrowRight className="h-4 w-4" />
        </Button>
        <p className="text-center text-[13px] text-ink-3">
          By continuing you agree to the <Link href="/terms" className="underline underline-offset-2">Terms</Link> and{" "}
          <Link href="/privacy" className="underline underline-offset-2">Privacy policy</Link>.
        </p>
      </form>
      <p className="mt-8 text-center text-[15px] text-ink-2">
        Already have an account?{" "}
        <Link href={`/login${sp.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`} className="font-medium text-ink underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ sign in
export function LoginForm() {
  const sp = useSearchParams();
  const next = safeNext(sp.get("next"));
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(sp.get("error"));
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"password" | "link" | "sent">("password");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "link") {
        await api("auth/magic-link", { body: { email: email.trim(), redirect_to: callbackUrl(next) } });
        setMode("sent");
      } else {
        await api("auth/login", { body: { email: email.trim(), password } });
        router.replace(next);
        router.refresh();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (mode === "sent") return <CheckInbox email={email} what="sign in" next={next} />;

  return (
    <div>
      <GoogleButton next={next} />
      <OrDivider />
      <form onSubmit={submit} className="space-y-5">
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required placeholder="you@university.edu" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        {mode === "password" && (
          <Field
            label="Password"
            htmlFor="password"
            aside={
              <Link href="/forgot-password" className="text-[13px] text-ink-2 underline underline-offset-4 hover:text-ink">
                Forgot password?
              </Link>
            }
          >
            <PasswordInput id="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
        )}
        {error && (
          <p className="border border-err/30 bg-err-soft px-3 py-2 text-sm text-err" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          {mode === "link" ? (
            <>
              <Mail className="h-4 w-4" /> Email me a sign-in link
            </>
          ) : (
            <>
              Sign in <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>
        <button type="button" onClick={() => setMode(mode === "link" ? "password" : "link")} className="block w-full text-center text-sm text-ink-2 underline underline-offset-4 hover:text-ink">
          {mode === "link" ? "Use my password instead" : "Sign in with an email link instead"}
        </button>
      </form>
      <p className="mt-8 text-center text-[15px] text-ink-2">
        New to Watchtower?{" "}
        <Link href={`/signup${sp.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`} className="font-medium text-ink underline underline-offset-4">
          Create an account
        </Link>
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ inbox + one-time code
export function CheckInbox({ email, what, next }: { email: string; what: string; next?: string }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const verify = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("auth/verify-otp", { body: { email, token: code.trim(), type: what === "sign in" ? "email" : "signup" } });
      router.replace(next || "/dashboard");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ticked border border-line bg-elevated/70 p-6" role="status">
      <Mail className="h-6 w-6 text-amber-ink" aria-hidden />
      <h2 className="mt-4 font-display text-[28px] leading-tight text-ink">Check your inbox</h2>
      <p className="mt-2 text-[15px] text-ink-2">
        We sent a link to <strong className="text-ink">{email}</strong> to {what}. Open it on this device, or enter the
        code from the email below.
      </p>
      <form onSubmit={verify} className="mt-5 flex gap-2">
        <label htmlFor="otp" className="sr-only">
          One-time code
        </label>
        <Input id="otp" inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 10))} className="font-mono tracking-[0.3em]" />
        <Button type="submit" loading={busy} disabled={code.length < 6}>
          Verify
        </Button>
      </form>
      {error && (
        <p className="mt-3 text-sm text-err" role="alert">
          {error}
        </p>
      )}
      <p className="mt-5 text-[13px] text-ink-3">Nothing after a minute? Check spam, or go back and try again.</p>
    </div>
  );
}

// ------------------------------------------------------------------ forgot / reset
export function ForgotForm() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("auth/password/recover", { body: { email: email.trim(), redirect_to: callbackUrl("/reset-password") } });
      setSent(true);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  if (sent)
    return (
      <div className="ticked border border-line bg-elevated/70 p-6" role="status">
        <Mail className="h-6 w-6 text-amber-ink" aria-hidden />
        <h2 className="mt-4 font-display text-[28px] text-ink">Check your inbox</h2>
        <p className="mt-2 text-[15px] text-ink-2">
          If an account exists for <strong className="text-ink">{email}</strong>, a reset link is on its way.
        </p>
        <Link href="/login" className="mt-5 inline-block text-sm text-ink underline underline-offset-4">
          Back to sign in
        </Link>
      </div>
    );
  return (
    <form onSubmit={submit} className="space-y-5">
      <Field label="Email" htmlFor="email">
        <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@university.edu" />
      </Field>
      <Button type="submit" size="lg" className="w-full" loading={busy}>
        Send reset link
      </Button>
      <p className="text-center text-[15px] text-ink-2">
        Remembered it?{" "}
        <Link href="/login" className="font-medium text-ink underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </form>
  );
}

export function ResetForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const p = passwordProblem(password);
    if (p) return setError(p);
    if (password !== confirm) return setError("The passwords don't match.");
    setError(null);
    setBusy(true);
    try {
      await api("auth/password", { body: { password } });
      toast.success("Password updated");
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError && err.isAuth ? "Your reset link expired. Request a new one." : errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5">
      <Field label="New password" htmlFor="password" hint="At least 8 characters, mixing letters with numbers or symbols.">
        <PasswordInput id="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <Field label="Confirm password" htmlFor="confirm">
        <PasswordInput id="confirm" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      {error && (
        <p className="border border-err/30 bg-err-soft px-3 py-2 text-sm text-err" role="alert">
          {error}{" "}
          {error.includes("expired") && (
            <Link href="/forgot-password" className="underline">
              Get a new link
            </Link>
          )}
        </p>
      )}
      <Button type="submit" size="lg" className="w-full" loading={busy}>
        Update password
      </Button>
    </form>
  );
}
