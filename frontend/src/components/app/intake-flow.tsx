"use client";

import {
  AlertTriangle,
  ArrowRight,
  Bell,
  Check,
  CircleHelp,
  Clock,
  Database,
  FileText,
  Globe,
  Link2,
  Mail,
  Pencil,
  RotateCcw,
  Send,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Users,
  Wand2,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { SubscribeButton } from "@/components/community/watch-card";
import { Button } from "@/components/ui/button";
import { Coordinates, Crosshair, Kicker, SectionLabel } from "@/components/ui/display";
import { Input, NativeSelect, Textarea } from "@/components/ui/field";
import { Switch } from "@/components/ui/primitives";
import { RadarMini } from "@/components/ui/spinner";
import { ApiError, errorMessage } from "@/lib/api";
import { useIntake, useIntakeStep, useMe, useStartIntake } from "@/lib/queries";
import type { IntakeProposal, IntakeSession, Predicate } from "@/lib/types";
import { cn, formatInterval, hostOf } from "@/lib/utils";

import { PageFrame } from "./app-shell";

const EXAMPLES = [
  { label: "Exam results", q: "Tell me when SSC CGL 2026 Tier-1 result is declared" },
  { label: "Job openings", q: "New SDE-1 backend roles at Razorpay, Zerodha or Swiggy in Bengaluru" },
  { label: "Price drops", q: "Sony WH-1000XM5 drops below ₹22,000 on Amazon India" },
  { label: "Scholarships", q: "When the NSP 2026-27 scholarship portal opens for post-matric" },
  { label: "Govt notices", q: "New circulars from RBI about UPI limits" },
];

const STAGES = [
  { key: "understanding", label: "Understanding your request" },
  { key: "searching", label: "Finding official sources" },
  { key: "checking_pages", label: "Checking the pages" },
  { key: "testing", label: "Testing against the live page" },
];

const INTERVALS = [15, 30, 60, 120, 180, 360, 720, 1440, 4320, 10080];

const TASK_LABEL: Record<string, string> = {
  extract_details: "Extract key details",
  deadlines: "Find deadlines",
  compare: "Compare with last time",
  checklist: "Make a checklist",
  draft_message: "Draft a message",
};

function ruleText(p: Predicate): string {
  const vals = (p.values || []).slice(0, 4).map((v) => `“${v}”`).join(", ");
  switch (p.type) {
    case "contains_any":
      return `Page mentions any of ${vals}`;
    case "contains_all":
      return `Page mentions all of ${vals}`;
    case "not_contains":
      return `Ignore if it mentions ${vals}`;
    case "price_below":
      return `Price below ₹${p.threshold?.toLocaleString("en-IN")}`;
    case "price_above":
      return `Price above ₹${p.threshold?.toLocaleString("en-IN")}`;
    case "number_below":
      return `${p.label || "Number"} below ${p.threshold}`;
    case "number_above":
      return `${p.label || "Number"} above ${p.threshold}`;
    case "new_items":
      return vals ? `New items mentioning ${vals}` : "New items appear in the list";
    case "in_stock":
      return "Back in stock";
    case "regex":
      return `Matches pattern ${p.pattern}`;
    case "text_changed":
      return "The watched text changes";
    default:
      return p.type;
  }
}

export function IntakeFlow() {
  const router = useRouter();
  const sp = useSearchParams();
  const sessionId = sp.get("session");
  const start = useStartIntake();
  const intake = useIntake(sessionId);
  const [text, setText] = useState(sp.get("q") || "");
  const autoStarted = useRef(false);

  const begin = (q: string) => {
    const query = q.trim();
    if (!query) return;
    start.mutate(query, {
      onSuccess: (s) => router.replace(`/watches/new?session=${s.id}`, { scroll: false }),
      onError: (e) => {
        if (e instanceof ApiError && e.isQuota) toast.error("Daily limit reached", { description: e.message });
        else toast.error(errorMessage(e));
      },
    });
  };

  useEffect(() => {
    const q = sp.get("q");
    if (q && !sessionId && !autoStarted.current) {
      autoStarted.current = true;
      begin(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const session = intake.data;
  const reset = () => {
    setText("");
    router.replace("/watches/new");
  };

  return (
    <PageFrame>
      <div className="grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1fr)_200px]">
        <div className="min-w-0">
          <SectionLabel index={1}>Tell us what to watch</SectionLabel>
          <h1 className="mt-5 font-display text-[clamp(2.4rem,5vw,4.4rem)] leading-[0.96] text-ink">
            Describe what you want
            <br />
            to <em className="accent">keep an eye on.</em>
          </h1>

          <QueryBox
            value={session ? session.query : text}
            onChange={setText}
            onSubmit={() => begin(text)}
            locked={Boolean(session)}
            busy={start.isPending}
            onEdit={reset}
          />
          {!session && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-sm text-ink-3">Try an example:</span>
              {EXAMPLES.map((e) => (
                <button key={e.label} onClick={() => setText(e.q)} className="border border-line-strong/70 bg-elevated/50 px-3 py-1.5 text-[13px] text-ink-2 transition-colors hover:border-ink hover:text-ink">
                  {e.label}
                </button>
              ))}
            </div>
          )}

          {sessionId && (
            <section className="mt-12" aria-live="polite">
              <SectionLabel index={2}>Here&apos;s what I&apos;ll do</SectionLabel>
              <div className="mt-5">
                {intake.isPending ? (
                  <AgentCard>
                    <Working stage="queued" message="Loading…" />
                  </AgentCard>
                ) : intake.isError ? (
                  <AgentCard>
                    <Outcome tone="err" title="Couldn't load this request" message={errorMessage(intake.error)} onRestart={reset} />
                  </AgentCard>
                ) : session ? (
                  <SessionView session={session} onRestart={reset} onTry={(q) => { reset(); setTimeout(() => begin(q), 0); }} />
                ) : null}
              </div>
            </section>
          )}
          {!sessionId && <HowItHelps />}
        </div>
        <aside className="hidden flex-col items-end gap-8 pt-2 xl:flex" aria-hidden>
          <Kicker className="text-right" lines={["Same web.", "More signals.", "A more", "informed you."]} />
          <Crosshair size={44} />
          <div className="label-mono mt-24 text-right text-[10px] text-ink-3">
            [03]
            <br />
            From signals
            <br />
            to opportunities
          </div>
          <Coordinates className="text-right" />
        </aside>
      </div>
    </PageFrame>
  );
}

function QueryBox({ value, onChange, onSubmit, locked, busy, onEdit }: { value: string; onChange: (v: string) => void; onSubmit: () => void; locked: boolean; busy: boolean; onEdit: () => void }) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="ticked relative mt-8 border border-line-strong bg-elevated/80 shadow-card"
    >
      <label htmlFor="intake-q" className="sr-only">
        What should Watchtower watch?
      </label>
      <textarea
        id="intake-q"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey || !e.shiftKey) && !locked) {
            e.preventDefault();
            onSubmit();
          }
        }}
        readOnly={locked}
        maxLength={1000}
        rows={3}
        placeholder="Notify me when new software engineering internships are posted at top product companies (like Google, Microsoft, Amazon) for Summer 2027."
        className="mono-tight block min-h-[120px] w-full resize-none bg-transparent px-5 py-5 pr-20 text-[14.5px] leading-relaxed text-ink placeholder:text-ink-3/80 focus-visible:outline-none read-only:text-ink-2"
      />
      <div className="absolute bottom-4 right-4 flex items-center gap-2">
        {locked ? (
          <Button type="button" variant="ghost" size="sm" onClick={onEdit} aria-label="Start over with a new request">
            <RotateCcw className="h-4 w-4" /> New
          </Button>
        ) : (
          <Button type="submit" size="icon" loading={busy} disabled={!value.trim()} aria-label="Ask the agent">
            <ArrowRight className="h-5 w-5" />
          </Button>
        )}
      </div>
    </form>
  );
}

function AgentCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn("ticked border border-line-strong bg-elevated/80 p-5 shadow-card sm:p-7", className)}
    >
      {children}
    </motion.div>
  );
}

function AgentHeader({ subtitle, action }: { subtitle: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line pb-5">
      <div className="flex items-start gap-3">
        <Sparkles className="mt-1 h-6 w-6 text-amber" aria-hidden />
        <div>
          <div className="font-display text-[24px] leading-tight text-ink">Watchtower Agent</div>
          <p className="text-[15px] text-ink-2">{subtitle}</p>
        </div>
      </div>
      {action}
    </div>
  );
}

function SessionView({ session, onRestart, onTry }: { session: IntakeSession; onRestart: () => void; onTry: (q: string) => void }) {
  const v = session.view || {};
  switch (session.status) {
    case "queued":
    case "running":
      return (
        <AgentCard>
          <Working stage={session.stage || "queued"} message={v.message} />
        </AgentCard>
      );
    case "awaiting_user":
      return <Questions session={session} />;
    case "proposed":
      return <Proposal session={session} />;
    case "created":
      return <Created session={session} />;
    case "refused":
      return (
        <AgentCard>
          <Outcome tone="err" icon={<ShieldCheck className="h-6 w-6" />} title="I can't set this one up" message={v.message} onRestart={onRestart} />
        </AgentCard>
      );
    case "rejected":
      return (
        <AgentCard>
          <Outcome tone="amber" icon={<CircleHelp className="h-6 w-6" />} title="This can't be watched as written" message={v.message} alternatives={v.alternatives} onTry={onTry} onRestart={onRestart} />
        </AgentCard>
      );
    case "cancelled":
      return (
        <AgentCard>
          <Outcome tone="idle" title="Cancelled" message={v.message || "No watch was created."} onRestart={onRestart} />
        </AgentCard>
      );
    default:
      return (
        <AgentCard>
          <Outcome tone="err" icon={<AlertTriangle className="h-6 w-6" />} title="That didn't work" message={v.message || "Something went wrong."} onRestart={onRestart} retryQuery={session.query} onTry={onTry} />
        </AgentCard>
      );
  }
}

function Working({ stage, message }: { stage: string; message?: string }) {
  const idx = Math.max(0, STAGES.findIndex((s) => s.key === stage));
  const started = stage !== "queued";
  return (
    <div>
      <AgentHeader subtitle={message || "Working on it…"} action={<RadarMini />} />
      <ol className="mt-6 space-y-4">
        {STAGES.map((s, k) => {
          const done = started && k < idx;
          const active = started ? k === idx : k === 0;
          return (
            <li key={s.key} className={cn("flex items-center gap-4 text-[15px]", done ? "text-ink-2" : active ? "text-ink" : "text-ink-3")}>
              <span className={cn("grid h-6 w-6 place-items-center rounded-full border", done ? "border-ok bg-ok text-white dark:text-bg" : active ? "border-amber" : "border-line-strong")}>
                {done ? <Check className="h-3.5 w-3.5" /> : active ? <span className="h-2 w-2 animate-blink rounded-full bg-amber" /> : null}
              </span>
              {s.label}
              {active && <span className="mono-tight text-[12px] text-ink-3">working…</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-6 text-[13px] text-ink-3">This usually takes 10 to 40 seconds. You can leave this page; we&apos;ll keep going and you can come back to it.</p>
    </div>
  );
}

function Questions({ session }: { session: IntakeSession }) {
  const step = useIntakeStep(session.id);
  const v = session.view;
  const qs = v.questions ?? [];
  const isUrl = session.stage === "need_url";
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const ready = qs.every((q) => (answers[q.id] || "").trim());

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    step.mutate({ step: "answer", body: { answers } }, { onError: (err) => toast.error(errorMessage(err)) });
  };
  const cancel = () => step.mutate({ step: "cancel" }, { onError: (err) => toast.error(errorMessage(err)) });

  return (
    <AgentCard>
      <AgentHeader subtitle={v.message || "A quick question so I watch the right thing:"} />
      <form onSubmit={submit} className="mt-6 space-y-7">
        {isUrl && v.failed_sources && v.failed_sources.length > 0 && (
          <div className="border border-line bg-bg/50 p-4 text-sm">
            <p className="label-mono text-ink-3">Pages I tried</p>
            <ul className="mt-2 space-y-1.5">
              {v.failed_sources.map((f) => (
                <li key={f.url} className="flex gap-2 text-ink-2">
                  <X className="mt-0.5 h-4 w-4 shrink-0 text-err" aria-hidden />
                  <span className="min-w-0 truncate">{hostOf(f.url)}</span>
                  {f.reason && <span className="shrink-0 text-ink-3">· {f.reason}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {qs.map((q, k) => (
          <fieldset key={q.id} className="flex flex-col gap-3 sm:flex-row sm:gap-6">
            <legend className="sr-only">{q.question}</legend>
            <div className="flex w-56 shrink-0 items-start gap-3">
              <CircleHelp className="mt-0.5 h-5 w-5 text-ink-2" aria-hidden />
              <span className="font-medium text-ink">{isUrl ? "Which page?" : qs.length > 1 ? `Question ${k + 1}` : "Quick question"}</span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[15px] text-ink-2">{q.question}</p>
              {q.options.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label={q.question}>
                  {q.options.map((o) => {
                    const on = answers[q.id] === o;
                    return (
                      <button
                        type="button"
                        key={o}
                        role="radio"
                        aria-checked={on}
                        onClick={() => setAnswers((a) => ({ ...a, [q.id]: o }))}
                        className={cn(
                          "flex items-center gap-2 border px-3.5 py-2 text-[14px] transition-colors",
                          on ? "border-amber bg-amber-soft text-ink" : "border-line-strong/70 bg-bg/40 text-ink-2 hover:border-ink hover:text-ink",
                        )}
                      >
                        {on && <Sparkles className="h-3.5 w-3.5 text-amber" aria-hidden />}
                        {o}
                      </button>
                    );
                  })}
                </div>
              )}
              <div className="mt-3">
                {isUrl ? (
                  <Input type="url" inputMode="url" placeholder="https://…" aria-label="Page link" value={answers[q.id] || ""} onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} />
                ) : (
                  <Input
                    placeholder={q.options.length ? "Or type your own answer" : "Your answer"}
                    aria-label={`Answer: ${q.question}`}
                    value={q.options.includes(answers[q.id] || "") ? "" : answers[q.id] || ""}
                    onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                    maxLength={300}
                  />
                )}
              </div>
            </div>
          </fieldset>
        ))}
        <div className="flex flex-col-reverse gap-3 border-t border-line pt-6 sm:flex-row sm:justify-between">
          <Button type="button" variant="ghost" onClick={cancel} disabled={step.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="amber" size="lg" mono loading={step.isPending} disabled={!ready}>
            Continue <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </form>
    </AgentCard>
  );
}

function Proposal({ session }: { session: IntakeSession }) {
  const router = useRouter();
  const me = useMe();
  const step = useIntakeStep(session.id);
  const p = session.view.proposal as IntakeProposal;
  const dry = session.view.dry_run;
  const similar = session.view.similar_public_watches ?? [];
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(p.title);
  const [condition, setCondition] = useState(p.condition);
  const [interval, setInterval] = useState(p.interval_minutes);
  const [deliveryChoice, setDelivery] = useState<"instant" | "digest" | null>(null);
  const delivery = deliveryChoice ?? me.data?.default_delivery_mode ?? "instant";
  const [visibility, setVisibility] = useState<"private" | "unlisted" | "public">("private");
  const [fireOnce, setFireOnce] = useState(p.fire_once);

  const intervals = useMemo(() => {
    const set = new Set(INTERVALS.filter((m) => m >= p.min_interval_minutes));
    set.add(p.interval_minutes);
    return [...set].sort((a, b) => a - b);
  }, [p.interval_minutes, p.min_interval_minutes]);

  const confirm = () => {
    const edits: Record<string, unknown> = { delivery_mode: delivery, visibility };
    if (title.trim() && title.trim() !== p.title) edits.title = title.trim();
    if (condition.trim() && condition.trim() !== p.condition) edits.condition = condition.trim();
    if (interval !== p.interval_minutes) edits.interval_minutes = interval;
    if (fireOnce !== p.fire_once) edits.fire_once = fireOnce;
    step.mutate(
      { step: "confirm", body: { confirm: true, edits } },
      {
        onError: (e) => {
          if (e instanceof ApiError && e.isQuota) {
            toast.error("Plan limit reached", { description: e.message, action: { label: "See plans", onClick: () => router.push("/settings?tab=plan") } });
          } else toast.error(errorMessage(e));
        },
      },
    );
  };
  const decline = () => step.mutate({ step: "confirm", body: { confirm: false } });
  const channels = me.data?.default_channels ?? ["email"];
  const CH: Record<string, { icon: typeof Mail; label: string }> = {
    email: { icon: Mail, label: "Email" },
    push: { icon: Smartphone, label: "Push" },
    telegram: { icon: Send, label: "Telegram" },
    webhook: { icon: Link2, label: "Webhook" },
  };

  return (
    <AgentCard>
      <AgentHeader
        subtitle={session.view.message || "I've set this up based on your request. Here's what I'll do:"}
        action={
          <Button variant="ghost" size="sm" onClick={() => setEditing((e) => !e)} aria-pressed={editing}>
            <Pencil className="h-4 w-4" /> {editing ? "Done" : "Modify"}
          </Button>
        }
      />

      {dry?.already_met && (
        <div className="mt-5 flex gap-3 border border-amber/60 bg-amber-soft/60 p-4 text-[14.5px]" role="status">
          <Bell className="mt-0.5 h-5 w-5 shrink-0 text-amber-ink" aria-hidden />
          <div>
            <p className="font-medium text-ink">Heads up: this looks true already.</p>
            <p className="mt-1 text-ink-2">{dry.reason}</p>
            {dry.evidence && <blockquote className="mono-tight mt-2 border-l-2 border-amber pl-3 text-[12.5px] text-ink-2">“{dry.evidence}”</blockquote>}
          </div>
        </div>
      )}

      {similar.length > 0 && (
        <div className="mt-5 border border-line bg-bg/50 p-4">
          <p className="flex items-center gap-2 text-[14.5px] font-medium text-ink">
            <Users className="h-4 w-4 text-ink-2" aria-hidden /> The community already watches something similar
          </p>
          <ul className="mt-3 space-y-2">
            {similar.slice(0, 3).map((s) => (
              <li key={s.watch_id} className="flex flex-wrap items-center justify-between gap-3">
                <Link href={`/community/${s.slug}`} className="text-[15px] text-ink underline underline-offset-4">
                  {s.title}
                </Link>
                <span className="flex items-center gap-3 text-sm text-ink-3">
                  {s.subscribers} subscribers
                  <SubscribeButton watch={{ id: s.watch_id, slug: s.slug, title: s.title }} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-2 grid grid-cols-1 divide-line md:grid-cols-2 md:divide-x">
        <Block icon={<FileText />} title="Understood condition" className="md:pr-7">
          {editing ? (
            <div className="space-y-3">
              <Input aria-label="Watch title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={140} />
              <Textarea aria-label="Condition" value={condition} onChange={(e) => setCondition(e.target.value)} maxLength={600} rows={4} />
            </div>
          ) : (
            <>
              <p className="font-medium text-ink">{title}</p>
              <p className="mt-1">{condition}</p>
            </>
          )}
          {p.rules.length > 0 && (
            <ul className="mt-3 space-y-1">
              {p.rules.map((r, k) => (
                <li key={k} className="mono-tight flex gap-2 text-[12px] text-ink-3">
                  <span aria-hidden>›</span>
                  {ruleText(r)}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 flex items-center gap-2 text-[13px] text-ink-3">
            <Wand2 className="h-3.5 w-3.5" aria-hidden />
            {p.uses_ai_judgement ? "AI judges relevant changes; unchanged pages are skipped for free." : "Decided by exact rules: no AI needed per check."}
          </p>
        </Block>
        <Block icon={<Database />} title="Sources to watch" className="md:pl-7">
          <div className="flex flex-wrap gap-2">
            {p.sources.map((s) => (
              <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1.5 bg-sunken px-3 py-1.5 text-[13.5px] text-ink hover:underline" title={s.url}>
                <Globe className="h-3.5 w-3.5 shrink-0 text-ink-3" aria-hidden />
                <span className="truncate">{s.label || hostOf(s.url)}</span>
              </a>
            ))}
          </div>
          {p.follow_up_tasks.length > 0 && (
            <p className="mt-4 text-[13.5px]">
              When it fires, I&apos;ll also: {p.follow_up_tasks.map((t) => TASK_LABEL[t] || t).join(" · ")}
            </p>
          )}
        </Block>
        <Block icon={<Clock />} title="Check frequency" className="border-t border-line md:pr-7">
          {editing ? (
            <NativeSelect aria-label="Check frequency" value={interval} onChange={(e) => setInterval(Number(e.target.value))}>
              {intervals.map((m) => (
                <option key={m} value={m}>
                  {formatInterval(m * 60)}
                </option>
              ))}
            </NativeSelect>
          ) : (
            <p className="text-ink">{formatInterval(interval * 60)}</p>
          )}
          <p className="mt-1">I&apos;ll check for changes and compare with the last snapshot.</p>
          <label className="mt-4 flex items-center gap-3 text-[14px] text-ink-2">
            <Switch checked={fireOnce} onCheckedChange={setFireOnce} label="Stop after the first alert" />
            Stop after the first alert
          </label>
        </Block>
        <Block icon={<Bell />} title="Alerts" className="border-t border-line md:pl-7">
          <div className="flex flex-wrap gap-2">
            {channels.map((c) => {
              const ch = CH[c] || { icon: Bell, label: c };
              return (
                <span key={c} className="inline-flex items-center gap-2 border border-amber/50 bg-amber-soft/50 px-3 py-1.5 text-[13.5px] text-ink">
                  <ch.icon className="h-4 w-4" aria-hidden /> {ch.label}
                </span>
              );
            })}
            <Link href="/settings?tab=notifications" className="self-center text-[13px] text-ink-2 underline underline-offset-4">
              Change
            </Link>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <NativeSelect aria-label="Delivery" value={delivery} onChange={(e) => setDelivery(e.target.value as "instant" | "digest")}>
              <option value="instant">Instantly</option>
              <option value="digest">Daily digest</option>
            </NativeSelect>
            <NativeSelect aria-label="Visibility" value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
              <option value="private">Private</option>
              <option value="unlisted">Unlisted link</option>
              <option value="public">Public (community)</option>
            </NativeSelect>
          </div>
          {visibility === "public" && <p className="mt-2 text-[13px]">Public watches are reviewed before they appear in Community.</p>}
        </Block>
      </div>

      {!dry?.already_met && dry && (
        <p className="mt-2 flex items-start gap-2 border-t border-line pt-4 text-[13.5px] text-ink-3">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden /> Live test: {dry.reason}
        </p>
      )}

      <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row">
        <Button variant="ghost" onClick={decline} disabled={step.isPending}>
          Don&apos;t create
        </Button>
        <Button variant="amber" size="lg" mono className="flex-1" onClick={confirm} loading={step.isPending}>
          Create watch <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </AgentCard>
  );
}

function Block({ icon, title, children, className }: { icon: React.ReactNode; title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex gap-4 py-6", className)}>
      <span className="mt-0.5 text-ink-2 [&>svg]:h-5 [&>svg]:w-5" aria-hidden>
        {icon}
      </span>
      <div className="min-w-0 flex-1 text-[14.5px] leading-relaxed text-ink-2">
        <h3 className="mb-2 text-[16px] font-medium text-ink">{title}</h3>
        {children}
      </div>
    </div>
  );
}

function Created({ session }: { session: IntakeSession }) {
  const router = useRouter();
  const id = session.watch_id || session.view.watch_id;
  useEffect(() => {
    if (!id) return;
    const t = setTimeout(() => router.push(`/watches/${id}`), 2600);
    return () => clearTimeout(t);
  }, [id, router]);
  return (
    <AgentCard>
      <div className="flex flex-col items-center py-6 text-center">
        <motion.span initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 260, damping: 18 }} className="grid h-16 w-16 place-items-center rounded-full bg-ok text-white dark:text-bg">
          <Check className="h-8 w-8" />
        </motion.span>
        <h3 className="mt-5 font-display text-[34px] leading-tight text-ink">Your watch is live.</h3>
        <p className="mt-2 max-w-md text-ink-2">
          {session.view.title ? <>“{session.view.title}” is now being watched. </> : null}
          Opening the live view…
        </p>
        <div className="mt-6 flex gap-3">
          {id && (
            <Button asChild mono>
              <Link href={`/watches/${id}`}>
                Open live view <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          )}
          <Button asChild variant="outline" mono>
            <Link href="/watches/new">Create another</Link>
          </Button>
        </div>
      </div>
    </AgentCard>
  );
}

function Outcome({
  tone,
  icon,
  title,
  message,
  alternatives,
  onTry,
  onRestart,
  retryQuery,
}: {
  tone: "err" | "amber" | "idle";
  icon?: React.ReactNode;
  title: string;
  message?: string;
  alternatives?: string[];
  onTry?: (q: string) => void;
  onRestart: () => void;
  retryQuery?: string;
}) {
  return (
    <div>
      <div className="flex items-start gap-4">
        <span className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-full", tone === "err" ? "bg-err-soft text-err" : tone === "amber" ? "bg-amber-soft text-amber-ink" : "bg-sunken text-ink-2")}>
          {icon || <AlertTriangle className="h-5 w-5" />}
        </span>
        <div>
          <h3 className="font-display text-[26px] leading-tight text-ink">{title}</h3>
          {message && <p className="mt-1.5 text-[15px] text-ink-2">{message}</p>}
        </div>
      </div>
      <AnimatePresence>
        {alternatives && alternatives.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-6 border-t border-line pt-5">
            <p className="label-mono text-ink-3">You could watch this instead</p>
            <ul className="mt-3 space-y-2">
              {alternatives.map((a) => (
                <li key={a}>
                  <button onClick={() => onTry?.(a)} className="group flex w-full items-center justify-between gap-3 border border-line bg-bg/50 px-4 py-3 text-left text-[15px] text-ink transition-colors hover:border-ink">
                    {a}
                    <ArrowRight className="h-4 w-4 shrink-0 text-ink-3 transition-transform group-hover:translate-x-1" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="mt-6 flex flex-wrap gap-3">
        {retryQuery && onTry && (
          <Button mono onClick={() => onTry(retryQuery)}>
            <RotateCcw className="h-4 w-4" /> Try again
          </Button>
        )}
        <Button variant="outline" mono onClick={onRestart}>
          Describe something else
        </Button>
      </div>
    </div>
  );
}

function HowItHelps() {
  return (
    <div className="mt-14 grid grid-cols-1 gap-px border border-line bg-line sm:grid-cols-3">
      {[
        { icon: CircleHelp, t: "Asks when unsure", d: "Vague requests get one or two quick questions, never a guess." },
        { icon: Globe, t: "Finds official pages", d: "Prefers primary sources, then tests the page live before you confirm." },
        { icon: ShieldCheck, t: "Stays on the right side", d: "Public information only. Private people and logins are off limits." },
      ].map((x) => (
        <div key={x.t} className="bg-bg p-5">
          <x.icon className="h-5 w-5 text-ink-2" aria-hidden />
          <p className="mt-3 font-medium text-ink">{x.t}</p>
          <p className="mt-1 text-[14px] text-ink-2">{x.d}</p>
        </div>
      ))}
    </div>
  );
}
