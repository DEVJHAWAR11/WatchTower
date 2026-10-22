"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  ExternalLink,
  KeyRound,
  Link2,
  Mail,
  Plus,
  Send,
  Smartphone,
  Trash2,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Pricing } from "@/components/marketing/pricing";
import { Button } from "@/components/ui/button";
import { Badge, Card, ErrorState, Meter, Skeleton, StatusDot } from "@/components/ui/display";
import { Field, Input, NativeSelect } from "@/components/ui/field";
import { Dialog, DialogContent, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { PageLoader } from "@/components/ui/spinner";
import { ApiError, api, errorMessage } from "@/lib/api";
import { qk, useApiTokens, useChannels, useDeliveries, useMe, usePlans, useUpdateSettings, useUsage } from "@/lib/queries";
import { currentPushSubscription, disablePush, enablePush, pushSupported } from "@/lib/push";
import type { Channel, Profile } from "@/lib/types";
import { formatDate, relativeTime } from "@/lib/utils";

import { PageFrame, PageHeader } from "./app-shell";

const TABS = ["profile", "notifications", "plan", "developer", "privacy"] as const;

export function SettingsPage() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = (TABS as readonly string[]).includes(sp.get("tab") || "") ? (sp.get("tab") as string) : "profile";
  const me = useMe();
  return (
    <PageFrame>
      <PageHeader
        kicker="/ Settings"
        title={
          <>
            Tune your <em className="accent">tower.</em>
          </>
        }
        subtitle="Your profile, how alerts reach you, your plan, and your data."
      />
      {me.isError ? (
        <ErrorState className="mt-10" error={me.error} onRetry={() => me.refetch()} />
      ) : !me.data ? (
        <PageLoader />
      ) : (
        <Tabs value={tab} onValueChange={(t) => router.replace(`/settings?tab=${t}`, { scroll: false })} className="mt-10">
          <TabsList>
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="notifications">Notifications</TabsTrigger>
            <TabsTrigger value="plan">Plan & usage</TabsTrigger>
            <TabsTrigger value="developer">Developer</TabsTrigger>
            <TabsTrigger value="privacy">Data & privacy</TabsTrigger>
          </TabsList>
          <div className="max-w-5xl pt-10">
            <TabsContent value="profile">
              <ProfileTab me={me.data} />
            </TabsContent>
            <TabsContent value="notifications">
              <NotificationsTab me={me.data} />
            </TabsContent>
            <TabsContent value="plan">
              <PlanTab me={me.data} />
            </TabsContent>
            <TabsContent value="developer">
              <DeveloperTab />
            </TabsContent>
            <TabsContent value="privacy">
              <PrivacyTab />
            </TabsContent>
          </div>
        </Tabs>
      )}
    </PageFrame>
  );
}

function Section({ title, description, children, id }: { title: string; description?: React.ReactNode; children: React.ReactNode; id?: string }) {
  return (
    <section id={id} className="grid grid-cols-1 gap-6 border-b border-line py-9 first:pt-0 last:border-0 lg:grid-cols-[280px_1fr]">
      <div>
        <h2 className="font-display text-[26px] leading-tight text-ink">{title}</h2>
        {description && <div className="mt-1.5 text-[14px] text-ink-2">{description}</div>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function fieldError(e: unknown): string {
  if (e instanceof ApiError && Array.isArray(e.details) && e.details.length) {
    const d = e.details[0] as { msg?: string };
    return (d.msg || e.message).replace(/^Value error, /, "");
  }
  return errorMessage(e);
}

// ------------------------------------------------------------------ profile
function ProfileTab({ me }: { me: Profile }) {
  const update = useUpdateSettings();
  const [name, setName] = useState(me.display_name || "");
  const [handle, setHandle] = useState(me.handle || "");
  const [tz, setTz] = useState(me.timezone);
  const [locale, setLocale] = useState(me.locale);
  const zones = useMemo(() => {
    let supported: string[] = [];
    try {
      supported = (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone");
    } catch {
      // older browsers: fall back to the short list below
    }
    // Browsers list canonical names (Chrome has Asia/Calcutta, not Asia/Kolkata), so make sure the saved zone and
    // the India default are always selectable.
    return Array.from(new Set(["Asia/Kolkata", me.timezone, "UTC", ...supported]));
  }, [me.timezone]);

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { display_name: name.trim() || null, timezone: tz, locale };
    if (handle.trim() && handle.trim() !== me.handle) body.handle = handle.trim().toLowerCase();
    update.mutate(body, { onSuccess: () => toast.success("Profile saved"), onError: (err) => toast.error(fieldError(err)) });
  };

  return (
    <div>
      <Section title="Profile" description="Your handle appears on watches you publish to Community.">
        <form onSubmit={save} className="space-y-5">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Field label="Display name" htmlFor="p-name">
              <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="name" />
            </Field>
            <Field label="Handle" htmlFor="p-handle" hint="3 to 32 characters: a–z, 0–9 and _">
              <div className="relative">
                <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-3">@</span>
                <Input id="p-handle" value={handle} onChange={(e) => setHandle(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))} maxLength={32} className="pl-8" />
              </div>
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Field label="Time zone" htmlFor="p-tz" hint="Used for quiet hours, digests and deadlines.">
              <NativeSelect id="p-tz" value={tz} onChange={(e) => setTz(e.target.value)}>
                {zones.map((z) => (
                  <option key={z} value={z}>
                    {z.replace(/_/g, " ")}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Language & region" htmlFor="p-loc">
              <NativeSelect id="p-loc" value={locale} onChange={(e) => setLocale(e.target.value)}>
                <option value="en-IN">English (India)</option>
                <option value="hi-IN">हिन्दी (India)</option>
                <option value="en-US">English (US)</option>
                <option value="en-GB">English (UK)</option>
              </NativeSelect>
            </Field>
          </div>
          <Button type="submit" loading={update.isPending}>
            Save profile
          </Button>
        </form>
      </Section>
      <Section title="Sign-in" description="Your email is managed by our identity provider.">
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <Mail className="h-4 w-4 text-ink-3" aria-hidden />
            <span className="text-ink">{me.email}</span>
            {me.email_verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="amber">Not verified</Badge>}
          </div>
          <ChangePassword />
        </div>
      </Section>
    </div>
  );
}

function ChangePassword() {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("auth/password", { body: { password: pw } });
      toast.success("Password updated");
      setPw("");
    } catch (err) {
      toast.error(fieldError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={save} className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <Field label="New password" htmlFor="new-pw" className="flex-1" hint="At least 8 characters, mixing letters with numbers or symbols.">
        <Input id="new-pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={8} />
      </Field>
      <Button type="submit" variant="outline" loading={busy} disabled={pw.length < 8} className="sm:mb-6">
        Change password
      </Button>
    </form>
  );
}

// ------------------------------------------------------------------ notifications
function NotificationsTab({ me }: { me: Profile }) {
  const qc = useQueryClient();
  const update = useUpdateSettings();
  const channels = useChannels();
  const usage = useUsage();
  const deliveries = useDeliveries();
  const allowed = (usage.data?.plan.features.channels ?? ["email", "push", "telegram"]) as Channel[];
  const maxPerHour = usage.data?.plan.limits.max_alerts_per_hour ?? 60;
  const [quiet, setQuiet] = useState(Boolean(me.quiet_hours_start));
  const [qs, setQs] = useState((me.quiet_hours_start || "22:00").slice(0, 5));
  const [qe, setQe] = useState((me.quiet_hours_end || "07:00").slice(0, 5));
  const [digest, setDigest] = useState(me.digest_time.slice(0, 5));
  const [perHour, setPerHour] = useState(me.max_alerts_per_hour);
  const [testBusy, setTestBusy] = useState(false);

  const patch = (body: Record<string, unknown>, ok: string) =>
    update.mutate(body, {
      onSuccess: () => {
        toast.success(ok);
        qc.invalidateQueries({ queryKey: qk.channels });
      },
      onError: (e) => toast.error(fieldError(e)),
    });

  const toggleDefault = (c: Channel) => {
    const set = new Set(me.default_channels);
    if (set.has(c)) set.delete(c);
    else set.add(c);
    if (!set.size) return toast.error("Keep at least one channel on.");
    patch({ default_channels: [...set] }, "Default channels updated");
  };

  const test = async () => {
    setTestBusy(true);
    try {
      const r = await api<{ queued: number }>("notifications/test", { method: "POST" });
      toast.success(r.queued ? `Test sent to ${r.queued} channel${r.queued > 1 ? "s" : ""}` : "No channels are ready yet");
      setTimeout(() => qc.invalidateQueries({ queryKey: qk.deliveries }), 2500);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setTestBusy(false);
    }
  };

  return (
    <div>
      <Section
        title="Channels"
        description={
          <>
            Where alerts go. Tick the ones to use by default.{" "}
            <button onClick={test} className="text-ink underline underline-offset-4" disabled={testBusy}>
              {testBusy ? "Sending…" : "Send a test"}
            </button>
          </>
        }
      >
        {channels.isError ? (
          <ErrorState error={channels.error} onRetry={() => channels.refetch()} />
        ) : !channels.data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <ul className="divide-y divide-line border border-line">
            <ChannelRow
              icon={<Mail />}
              name="Email"
              detail={channels.data.email.suppressed ? "Bounced or unsubscribed. Contact support to re-enable." : channels.data.email.address || "No email"}
              status={channels.data.email.enabled ? "on" : channels.data.email.suppressed ? "error" : "off"}
              isDefault={me.default_channels.includes("email")}
              onDefault={() => toggleDefault("email")}
              control={<Switch checked={me.email_alerts_enabled} onCheckedChange={(v) => patch({ email_alerts_enabled: v }, v ? "Email alerts on" : "Email alerts off")} label="Email alerts" />}
            />
            <PushRow
              available={channels.data.push.available}
              devices={channels.data.push.devices}
              vapid={channels.data.push.vapid_public_key}
              isDefault={me.default_channels.includes("push")}
              onDefault={() => toggleDefault("push")}
            />
            <TelegramRow
              available={channels.data.telegram.available && allowed.includes("telegram")}
              linked={channels.data.telegram.linked}
              username={channels.data.telegram.username}
              isDefault={me.default_channels.includes("telegram")}
              onDefault={() => toggleDefault("telegram")}
            />
          </ul>
        )}
      </Section>

      <Section title="Delivery" description="Instant alerts arrive as they happen. Digests bundle everything into one message a day.">
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Field label="Default delivery" htmlFor="n-mode">
              <NativeSelect id="n-mode" value={me.default_delivery_mode} onChange={(e) => patch({ default_delivery_mode: e.target.value }, "Delivery updated")}>
                <option value="instant">Instantly</option>
                <option value="digest">Daily digest</option>
              </NativeSelect>
            </Field>
            <Field label="Digest time" htmlFor="n-digest" hint={`In ${me.timezone.replace(/_/g, " ")}`}>
              <div className="flex gap-2">
                <Input id="n-digest" type="time" value={digest} onChange={(e) => setDigest(e.target.value)} />
                <Button variant="outline" onClick={() => patch({ digest_time: `${digest}:00` }, "Digest time saved")} disabled={digest === me.digest_time.slice(0, 5)}>
                  Save
                </Button>
              </div>
            </Field>
          </div>
          <div>
            <label className="flex items-center gap-3 text-[15px] text-ink">
              <Switch checked={quiet} onCheckedChange={(v) => { setQuiet(v); if (!v) patch({ clear_quiet_hours: true }, "Quiet hours off"); }} label="Quiet hours" />
              Quiet hours
            </label>
            <p className="mt-1 pl-14 text-[13.5px] text-ink-2">Instant alerts are held during these hours and delivered when they end.</p>
            {quiet && (
              <div className="mt-4 flex flex-wrap items-end gap-3 pl-14">
                <Field label="From" htmlFor="q-start">
                  <Input id="q-start" type="time" value={qs} onChange={(e) => setQs(e.target.value)} className="w-36" />
                </Field>
                <Field label="Until" htmlFor="q-end">
                  <Input id="q-end" type="time" value={qe} onChange={(e) => setQe(e.target.value)} className="w-36" />
                </Field>
                <Button variant="outline" className="mb-0" onClick={() => patch({ quiet_hours_start: `${qs}:00`, quiet_hours_end: `${qe}:00` }, "Quiet hours saved")}>
                  Save
                </Button>
              </div>
            )}
          </div>
          <Field label="At most this many alerts per hour" htmlFor="n-cap" hint={`Extra alerts go to your digest. Your plan allows up to ${maxPerHour}.`}>
            <div className="flex items-center gap-4">
              <input id="n-cap" type="range" min={1} max={maxPerHour} value={Math.min(perHour, maxPerHour)} onChange={(e) => setPerHour(Number(e.target.value))} className="w-64 accent-[var(--amber)]" />
              <span className="mono-tight w-8 text-ink">{Math.min(perHour, maxPerHour)}</span>
              <Button variant="outline" size="sm" onClick={() => patch({ max_alerts_per_hour: perHour }, "Saved")} disabled={perHour === me.max_alerts_per_hour}>
                Save
              </Button>
            </div>
          </Field>
        </div>
      </Section>

      <Section title="Self-tuning" description="Let your feedback improve watches automatically when a backtest shows it helps.">
        <div className="space-y-4">
          <label className="flex items-center gap-3 text-[15px] text-ink">
            <Switch checked={me.auto_tune} onCheckedChange={(v) => patch({ auto_tune: v }, v ? "Auto-tune on for all your watches" : "Auto-tune off")} label="Auto-tune" />
            Auto-tune my watches
            {!usage.data?.plan.features.auto_tune && <Badge>Plus</Badge>}
          </label>
          <label className="flex items-center gap-3 text-[15px] text-ink">
            <Switch checked={me.marketing_opt_in} onCheckedChange={(v) => patch({ marketing_opt_in: v }, "Saved")} label="Product updates" />
            Occasional product updates by email
          </label>
        </div>
      </Section>

      <Section title="Recent deliveries" description="The last notifications we sent you, with their status.">
        {deliveries.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : (deliveries.data ?? []).length === 0 ? (
          <p className="text-[14.5px] text-ink-2">Nothing sent yet.</p>
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {(deliveries.data ?? []).slice(0, 12).map((d) => (
              <li key={d.id} className="flex items-center gap-4 py-3 text-[14px]">
                <StatusDot tone={d.status === "sent" || d.status === "delivered" ? "ok" : d.status === "failed" ? "err" : "idle"} className="h-2 w-2" />
                <span className="w-20 capitalize text-ink">{d.channel}</span>
                <span className="flex-1 truncate text-ink-2">
                  {d.kind === "alert" ? "Alert" : d.kind === "digest" ? "Digest" : d.kind === "system" ? "Notice" : d.kind} · {d.status}
                  {d.status_reason ? ` · ${d.status_reason}` : ""}
                </span>
                <span className="text-ink-3">{relativeTime(d.sent_at || d.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function ChannelRow({ icon, name, detail, status, control, isDefault, onDefault, children }: { icon: React.ReactNode; name: string; detail: React.ReactNode; status: "on" | "off" | "error" | "na"; control?: React.ReactNode; isDefault?: boolean; onDefault?: () => void; children?: React.ReactNode }) {
  return (
    <li className="p-4 sm:p-5">
      <div className="flex items-start gap-4">
        <span className="mt-0.5 text-ink-2 [&>svg]:h-5 [&>svg]:w-5" aria-hidden>
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{name}</span>
            {status === "on" && <Badge tone="ok">Connected</Badge>}
            {status === "error" && <Badge tone="err">Problem</Badge>}
            {status === "na" && <Badge>Unavailable</Badge>}
          </div>
          <p className="mt-0.5 text-[14px] text-ink-2">{detail}</p>
          {children}
        </div>
        <div className="flex shrink-0 items-center gap-4">
          {onDefault && status !== "na" && (
            <label className="flex items-center gap-2 text-[13px] text-ink-2">
              <input type="checkbox" checked={Boolean(isDefault)} onChange={onDefault} className="h-4 w-4 accent-[var(--primary)]" />
              Default
            </label>
          )}
          {control}
        </div>
      </div>
    </li>
  );
}

function PushRow({ available, devices, vapid, isDefault, onDefault }: { available: boolean; devices: number; vapid: string | null; isDefault: boolean; onDefault: () => void }) {
  const qc = useQueryClient();
  const [here, setHere] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const supported = typeof window !== "undefined" && pushSupported();
  useEffect(() => {
    currentPushSubscription().then((s) => setHere(Boolean(s))).catch(() => setHere(false));
  }, []);
  const toggle = async () => {
    setBusy(true);
    try {
      if (here) {
        await disablePush();
        setHere(false);
        toast.success("Push turned off on this device");
      } else {
        if (!vapid) throw new Error("Push isn't configured on the server yet.");
        await enablePush(vapid);
        setHere(true);
        toast.success("Push is on for this device");
      }
      qc.invalidateQueries({ queryKey: qk.channels });
      qc.invalidateQueries({ queryKey: qk.me });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const status = !available || !supported ? "na" : devices > 0 ? "on" : "off";
  return (
    <ChannelRow
      icon={<Smartphone />}
      name="Push notifications"
      detail={
        !supported
          ? "This browser doesn't support push. On iPhone, add Watchtower to your Home Screen first."
          : !available
            ? "Push isn't available right now."
            : `${devices} device${devices === 1 ? "" : "s"} registered${here ? ", including this one" : ""}.`
      }
      status={status}
      isDefault={isDefault}
      onDefault={onDefault}
      control={
        supported && available ? (
          <Button size="sm" variant={here ? "outline" : "primary"} onClick={toggle} loading={busy || here === null}>
            {here ? "Turn off here" : "Enable on this device"}
          </Button>
        ) : null
      }
    />
  );
}

function TelegramRow({ available, linked, username, isDefault, onDefault }: { available: boolean; linked: boolean; username: string | null; isDefault: boolean; onDefault: () => void }) {
  const qc = useQueryClient();
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // While a link is open, poll until the bot confirms the chat.
  useEffect(() => {
    if (!link || linked) return;
    const t = setInterval(() => qc.invalidateQueries({ queryKey: qk.channels }), 3000);
    const stop = setTimeout(() => setLink(null), 10 * 60 * 1000);
    return () => {
      clearInterval(t);
      clearTimeout(stop);
    };
  }, [link, linked, qc]);
  // Once the bot confirms the chat, stop waiting (derived during render rather than in an effect).
  const [announced, setAnnounced] = useState(false);
  if (linked && link && !announced) {
    setAnnounced(true);
    setLink(null);
    toast.success("Telegram connected");
    qc.invalidateQueries({ queryKey: qk.me });
  }

  const connect = async () => {
    setBusy(true);
    try {
      const r = await api<{ deep_link: string }>("notifications/telegram/link", { method: "POST" });
      setLink(r.deep_link);
      window.open(r.deep_link, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const disconnect = async () => {
    setBusy(true);
    try {
      await api("notifications/telegram", { method: "DELETE" });
      toast.success("Telegram disconnected");
      qc.invalidateQueries({ queryKey: qk.channels });
      qc.invalidateQueries({ queryKey: qk.me });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ChannelRow
      icon={<Send />}
      name="Telegram"
      detail={!available ? "Telegram alerts aren't available right now." : linked ? `Linked${username ? ` to @${username}` : ""}.` : "Get alerts from our bot in Telegram."}
      status={!available ? "na" : linked ? "on" : "off"}
      isDefault={isDefault}
      onDefault={linked ? onDefault : undefined}
      control={
        available ? (
          linked ? (
            <Button size="sm" variant="outline" onClick={disconnect} loading={busy}>
              Disconnect
            </Button>
          ) : (
            <Button size="sm" onClick={connect} loading={busy}>
              Connect
            </Button>
          )
        ) : null
      }
    >
      {link && !linked && (
        <p className="mt-3 border border-amber/50 bg-amber-soft/50 px-3 py-2 text-[13.5px] text-ink" role="status">
          Waiting for you to press <strong>Start</strong> in Telegram…{" "}
          <a href={link} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">
            Open the bot again
          </a>
        </p>
      )}
    </ChannelRow>
  );
}

// ------------------------------------------------------------------ plan
function PlanTab({ me }: { me: Profile }) {
  const usage = useUsage();
  const plans = usePlans();
  const sp = useSearchParams();
  const wanted = sp.get("upgrade");
  const [requestFor, setRequestFor] = useState<string | null>(wanted && wanted !== me.plan_id ? wanted : null);
  const u = usage.data;
  return (
    <div>
      <Section title="Current plan" description={me.plan_expires_at ? `Renews or ends on ${formatDate(me.plan_expires_at)}.` : undefined}>
        {usage.isError ? (
          <ErrorState error={usage.error} onRetry={() => usage.refetch()} />
        ) : !u ? (
          <Skeleton className="h-56 w-full" />
        ) : (
          <Card className="p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <p className="font-display text-[34px] leading-none text-ink">{u.plan.name}</p>
              <p className="text-ink-2">{u.plan.price_usd_month ? `$${u.plan.price_usd_month}/month` : "Free forever"}</p>
            </div>
            <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2">
              <Meter label="Your watches" value={u.watches} max={u.plan.limits.max_watches} />
              <Meter label="Community subscriptions" value={u.subscriptions} max={u.plan.limits.max_subscriptions} />
              <Meter label="Follow-up actions this month" value={u.acts_this_month} max={u.plan.limits.acts_per_month} />
              <Meter label="Watches set up today" value={u.intake_today} max={u.plan.limits.intake_per_day} />
              <Meter label="Manual checks today" value={u.run_now_today} max={u.plan.limits.run_now_per_day} />
              <Meter label="AI tokens today" value={u.llm_tokens_today} max={u.plan.limits.llm_tokens_per_day} format={(n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))} />
            </div>
          </Card>
        )}
      </Section>
      <section className="pt-9">
        <h2 className="font-display text-[26px] text-ink">Plans</h2>
        <p className="mt-1 text-[14px] text-ink-2">Online payments are coming soon. Until then, request a plan and we&apos;ll switch you over, usually within a day.</p>
        <div className="mt-8">
          {plans.isPending ? <Skeleton className="h-96 w-full" /> : <PlanPicker plans={plans.data ?? null} current={me.plan_id} onRequest={setRequestFor} />}
        </div>
      </section>
      <PlanRequestDialog planId={requestFor} onClose={() => setRequestFor(null)} />
    </div>
  );
}

function PlanPicker({ plans, current, onRequest }: { plans: import("@/lib/types").Plan[] | null; current: string; onRequest: (id: string) => void }) {
  // Reuse the public pricing cards; intercept the upgrade links so they open the request dialog instead.
  return (
    <div
      onClickCapture={(e) => {
        const a = (e.target as HTMLElement).closest("a");
        const m = a?.getAttribute("href")?.match(/upgrade=(\w+)/);
        if (m) {
          e.preventDefault();
          e.stopPropagation();
          onRequest(m[1]);
        }
      }}
    >
      <Pricing plans={plans} currentPlan={current} />
    </div>
  );
}

function PlanRequestDialog({ planId, onClose }: { planId: string | null; onClose: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const submit = async () => {
    if (!planId) return;
    setBusy(true);
    try {
      await api("me/plan-request", { body: { plan_id: planId, note: note.trim() || null } });
      setDone(true);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={Boolean(planId)}
      onOpenChange={(o) => {
        if (!o) {
          onClose();
          setDone(false);
          setNote("");
        }
      }}
    >
      <DialogContent title={done ? "Request received" : `Switch to ${planId ? planId[0].toUpperCase() + planId.slice(1) : ""}`} description={done ? "We'll switch your plan and email you once it's active." : "Payments aren't live yet, so our team applies upgrades by hand. Add anything we should know."}>
        {done ? (
          <div className="flex justify-end">
            <Button onClick={onClose}>
              <Check className="h-4 w-4" /> Done
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <Field label="Note (optional)" htmlFor="plan-note">
              <Input id="plan-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="e.g. need faster checks for placement season" />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={submit} loading={busy}>
                Request plan
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ developer
function CopyOnce({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 border border-amber/60 bg-amber-soft/50 p-3">
      <p className="text-[13px] text-ink">{label}</p>
      <div className="mt-2 flex gap-2">
        <code className="mono-tight min-w-0 flex-1 overflow-x-auto whitespace-nowrap bg-bg px-3 py-2 text-[12px] text-ink">{value}</code>
        <Button
          size="sm"
          variant="outline"
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

function DeveloperTab() {
  const usage = useUsage();
  const channels = useChannels();
  const qc = useQueryClient();
  const proTokens = Boolean(usage.data?.plan.features.api_tokens);
  const proHooks = Boolean(usage.data?.plan.features.webhooks);
  const tokens = useApiTokens(proTokens);
  const [name, setName] = useState("");
  const [days, setDays] = useState("90");
  const [fresh, setFresh] = useState<string | null>(null);
  const [hookUrl, setHookUrl] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  if (!usage.data) return <Skeleton className="h-64 w-full" />;

  const createToken = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("token");
    try {
      const r = await api<{ token: string }>("me/api-tokens", { body: { name: name.trim(), expires_in_days: days === "never" ? null : Number(days) } });
      setFresh(r.token);
      setName("");
      qc.invalidateQueries({ queryKey: qk.tokens });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const revoke = async (id: string) => {
    setBusy(id);
    try {
      await api(`me/api-tokens/${id}`, { method: "DELETE" });
      toast.success("Token revoked");
      qc.invalidateQueries({ queryKey: qk.tokens });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const addHook = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("hook");
    try {
      const r = await api<{ secret: string }>("notifications/webhooks", { body: { url: hookUrl.trim() } });
      setSecret(r.secret);
      setHookUrl("");
      qc.invalidateQueries({ queryKey: qk.channels });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const delHook = async (id: string) => {
    setBusy(id);
    try {
      await api(`notifications/webhooks/${id}`, { method: "DELETE" });
      toast.success("Webhook removed");
      qc.invalidateQueries({ queryKey: qk.channels });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const upsell = (
    <Card className="flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-[15px] text-ink-2">API tokens and signed webhooks are part of the Pro plan.</p>
      <Button asChild variant="amber" mono>
        <Link href="/settings?tab=plan&upgrade=pro">Get Pro</Link>
      </Button>
    </Card>
  );

  return (
    <div>
      <Section
        title="API tokens"
        description={
          <>
            Use Watchtower from scripts and tools. See the{" "}
            <Link href="/docs" className="text-ink underline underline-offset-4">
              API docs <ExternalLink className="inline h-3 w-3" />
            </Link>
            .
          </>
        }
      >
        {!proTokens ? (
          upsell
        ) : (
          <div className="space-y-5">
            <form onSubmit={createToken} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field label="Token name" htmlFor="t-name" className="flex-1">
                <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. home server" maxLength={64} required />
              </Field>
              <Field label="Expires" htmlFor="t-exp">
                <NativeSelect id="t-exp" value={days} onChange={(e) => setDays(e.target.value)} className="w-36">
                  <option value="30">30 days</option>
                  <option value="90">90 days</option>
                  <option value="365">1 year</option>
                </NativeSelect>
              </Field>
              <Button type="submit" loading={busy === "token"}>
                <KeyRound className="h-4 w-4" /> Create
              </Button>
            </form>
            {fresh && <CopyOnce value={fresh} label="Copy your new token now. For your security it won't be shown again." />}
            {tokens.isPending ? (
              <Skeleton className="h-24 w-full" />
            ) : (tokens.data ?? []).length === 0 ? (
              <p className="text-[14px] text-ink-3">No tokens yet.</p>
            ) : (
              <ul className="divide-y divide-line border-y border-line">
                {(tokens.data ?? []).map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center gap-3 py-3 text-[14px]">
                    <KeyRound className="h-4 w-4 text-ink-3" aria-hidden />
                    <span className="font-medium text-ink">{t.name}</span>
                    <code className="mono-tight text-[12px] text-ink-3">{t.prefix}…</code>
                    <span className="flex-1 text-ink-3">
                      {t.revoked_at ? "Revoked" : t.last_used_at ? `Used ${relativeTime(t.last_used_at)}` : "Never used"}
                      {t.expires_at && !t.revoked_at ? ` · expires ${formatDate(t.expires_at)}` : ""}
                    </span>
                    {!t.revoked_at && (
                      <Button size="sm" variant="ghost" onClick={() => revoke(t.id)} loading={busy === t.id}>
                        <Trash2 className="h-4 w-4" /> Revoke
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Section>
      <Section title="Webhooks" description="We POST each alert as JSON, signed with your endpoint's secret.">
        {!proHooks ? (
          upsell
        ) : (
          <div className="space-y-5">
            <form onSubmit={addHook} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field label="HTTPS endpoint" htmlFor="h-url" className="flex-1">
                <Input id="h-url" type="url" value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} placeholder="https://example.com/hooks/watchtower" required />
              </Field>
              <Button type="submit" loading={busy === "hook"}>
                <Plus className="h-4 w-4" /> Add
              </Button>
            </form>
            {secret && <CopyOnce value={secret} label="Your signing secret. Store it now; it won't be shown again." />}
            <ul className="divide-y divide-line border-y border-line">
              {(channels.data?.webhook.endpoints ?? []).length === 0 && <li className="py-3 text-[14px] text-ink-3">No endpoints yet.</li>}
              {(channels.data?.webhook.endpoints ?? []).map((h) => (
                <li key={h.id} className="flex items-center gap-3 py-3 text-[14px]">
                  <Webhook className="h-4 w-4 text-ink-3" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-ink">{h.url}</span>
                  {h.active ? <Badge tone="ok">Active</Badge> : <Badge tone="err">Disabled</Badge>}
                  {h.failures > 0 && <span className="text-[12.5px] text-err">{h.failures} failures</span>}
                  <Button size="sm" variant="ghost" onClick={() => delHook(h.id)} loading={busy === h.id} aria-label={`Remove ${h.url}`}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>
      <Section title="Integrations" description="Link Telegram and push in Notifications.">
        <Button asChild variant="outline">
          <Link href="/settings?tab=notifications">
            <Link2 className="h-4 w-4" /> Notification channels
          </Link>
        </Button>
      </Section>
    </div>
  );
}

// ------------------------------------------------------------------ privacy
function PrivacyTab() {
  const qc = useQueryClient();
  const router = useRouter();
  const [exporting, setExporting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);

  const doExport = async () => {
    setExporting(true);
    try {
      const data = await api<Record<string, unknown>>("me/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `watchtower-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setExporting(false);
    }
  };
  const doDelete = async () => {
    setDeleting(true);
    try {
      await api("me", { method: "DELETE", query: { confirm: "DELETE" } });
      qc.clear();
      router.replace("/");
      router.refresh();
    } catch (e) {
      toast.error(errorMessage(e));
      setDeleting(false);
    }
  };

  return (
    <div>
      <Section title="Export your data" description="A JSON file with your profile, watches, versions, subscriptions, alerts, feedback and deliveries.">
        <Button variant="outline" onClick={doExport} loading={exporting}>
          <Download className="h-4 w-4" /> Download my data
        </Button>
      </Section>
      <Section title="Delete account" description="Permanent. Public watches others subscribe to are handed to the Watchtower Community account; everything else is erased.">
        <Button variant="danger" onClick={() => setConfirmOpen(true)}>
          <Trash2 className="h-4 w-4" /> Delete my account
        </Button>
        <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <DialogContent title="Delete your account?" description="This can't be undone. Your watches, alerts and settings will be erased.">
            <div className="space-y-4">
              <div className="flex gap-3 border border-err/30 bg-err-soft/60 p-3 text-[14px] text-ink">
                <AlertTriangle className="h-5 w-5 shrink-0 text-err" aria-hidden />
                Consider downloading your data first.
              </div>
              <Field label={<>Type <strong>DELETE</strong> to confirm</>} htmlFor="del-confirm">
                <Input id="del-confirm" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
              </Field>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
                  Cancel
                </Button>
                <Button variant="danger" disabled={typed !== "DELETE"} loading={deleting} onClick={doDelete}>
                  Delete forever
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </Section>
      <p className="text-[13px] text-ink-3">
        Read our{" "}
        <Link href="/privacy" className="underline underline-offset-4">
          privacy policy
        </Link>
        .
      </p>
    </div>
  );
}
