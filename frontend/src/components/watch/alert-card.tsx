"use client";

import {
  Bell,
  BellRing,
  CalendarPlus,
  Check,
  ChevronDown,
  ExternalLink,
  FileText,
  Link2,
  Mail,
  Quote,
  SlidersHorizontal,
  ThumbsDown,
  ThumbsUp,
  Wand2,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/display";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, Tooltip } from "@/components/ui/primitives";
import { Textarea } from "@/components/ui/field";
import { errorMessage } from "@/lib/api";
import { useActionDecision, useFeedback } from "@/lib/queries";
import type { Action, Alert } from "@/lib/types";
import { cn, formatDate, formatDateTime, hostOf, relativeTime, titleCase } from "@/lib/utils";

const ACTION_ICON: Record<string, typeof Bell> = {
  add_to_calendar: CalendarPlus,
  set_reminder: BellRing,
  open_link: ExternalLink,
  draft_email: Mail,
  create_followup_watch: Wand2,
  adjust_threshold: SlidersHorizontal,
};

function keyDetails(a: Alert): { label: string; value: string }[] {
  const kd = a.act_result?.key_details;
  const rows: { label: string; value: string }[] = [];
  if (Array.isArray(kd)) for (const r of kd) if (r && typeof r === "object" && "label" in r) rows.push({ label: String(r.label), value: String(r.value) });
  if (kd && !Array.isArray(kd)) for (const [k, v] of Object.entries(kd)) if (v !== null && v !== "") rows.push({ label: titleCase(k), value: String(v) });
  if (!rows.length && a.key_facts) {
    for (const [k, v] of Object.entries(a.key_facts)) {
      if (v === null || v === "" || typeof v === "object") continue;
      rows.push({ label: titleCase(k), value: String(v) });
    }
  }
  return rows.slice(0, 8);
}

function isUrl(s: string) {
  return /^https?:\/\//i.test(s);
}

export function FeedbackButtons({ alert, compact }: { alert: Alert; compact?: boolean }) {
  const fb = useFeedback();
  const [askWhy, setAskWhy] = useState(false);
  const [reason, setReason] = useState("");
  const send = (relevant: boolean, why?: string) =>
    fb.mutate(
      { alertId: alert.id, relevant, reason: why },
      {
        onSuccess: () => toast.success(relevant ? "Marked relevant" : "Marked not relevant", { description: "This tunes the watch over time." }),
        onError: (e) => toast.error(errorMessage(e)),
      },
    );
  const v = alert.my_feedback;
  return (
    <>
      <div className={cn("flex gap-2", compact ? "" : "sm:flex-col")} role="group" aria-label="Was this alert useful?">
        <Tooltip content="Relevant: more like this">
          <button
            onClick={() => send(true)}
            aria-pressed={v === true}
            aria-label="Relevant"
            className={cn("grid h-10 w-10 place-items-center border transition-colors", v === true ? "border-ok bg-ok-soft text-ok" : "border-line-strong text-ink-2 hover:border-ok hover:text-ok")}
          >
            <ThumbsUp className="h-4 w-4" />
          </button>
        </Tooltip>
        <Tooltip content="Not relevant: fewer like this">
          <button
            onClick={() => (v === false ? send(false) : setAskWhy(true))}
            aria-pressed={v === false}
            aria-label="Not relevant"
            className={cn("grid h-10 w-10 place-items-center border transition-colors", v === false ? "border-err bg-err-soft text-err" : "border-line-strong text-ink-2 hover:border-err hover:text-err")}
          >
            <ThumbsDown className="h-4 w-4" />
          </button>
        </Tooltip>
      </div>
      <Dialog open={askWhy} onOpenChange={setAskWhy}>
        <DialogContent title="Not relevant?" description="A word on why helps the agent tune this watch. Optional.">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(false, reason.trim() || undefined);
              setAskWhy(false);
              setReason("");
            }}
            className="space-y-4"
          >
            <div className="flex flex-wrap gap-2">
              {["Wrong location", "Wrong level or role", "Old news", "Already knew", "Not what I asked for"].map((r) => (
                <button type="button" key={r} onClick={() => setReason(r)} className={cn("border px-3 py-1.5 text-[13px]", reason === r ? "border-ink bg-ink text-bg" : "border-line-strong text-ink-2 hover:border-ink")}>
                  {r}
                </button>
              ))}
            </div>
            <Textarea aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. only Bengaluru roles, not Pune" />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setAskWhy(false)}>
                Cancel
              </Button>
              <Button type="submit">Send feedback</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ActionResult({ action }: { action: Action }) {
  const r = action.result || {};
  if (action.decision !== "executed" && action.decision !== "approved") return <span className="text-[13px] text-ink-3">{action.decision === "rejected" ? "Dismissed" : action.decision}</span>;
  if (typeof r.ics_url === "string")
    return (
      <a href={r.ics_url.replace(/^https?:\/\/[^/]+/, "")} className="inline-flex items-center gap-1.5 text-[13px] text-ok underline underline-offset-4">
        <Check className="h-3.5 w-3.5" /> Download calendar file
      </a>
    );
  if (typeof r.url === "string")
    return (
      <a href={r.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[13px] text-ok underline underline-offset-4">
        <Check className="h-3.5 w-3.5" /> Open link <ExternalLink className="h-3 w-3" />
      </a>
    );
  if (typeof r.remind_at === "string") return <span className="text-[13px] text-ok">✓ Reminder set for {formatDateTime(r.remind_at)}</span>;
  if (typeof r.intake_session_id === "string")
    return (
      <Link href={`/watches/new?session=${r.intake_session_id}`} className="text-[13px] text-ok underline underline-offset-4">
        ✓ Continue setting up the follow-up watch
      </Link>
    );
  if (r.version) return <span className="text-[13px] text-ok">✓ Applied as version {String(r.version)}</span>;
  return <span className="text-[13px] text-ok">✓ Done{action.kind === "draft_email" ? ": the draft is in your inbox" : ""}</span>;
}

export function ActionRow({ alert, action }: { alert: Alert; action: Action }) {
  const decide = useActionDecision();
  const Icon = ACTION_ICON[action.kind] || Wand2;
  const [now] = useState(() => Date.now());
  const expired = action.expires_at ? new Date(action.expires_at).getTime() < now : false;
  const go = (decision: "approve" | "reject") =>
    decide.mutate(
      { alertId: alert.id, actionId: action.id, decision },
      {
        onSuccess: (res) => {
          if (decision === "approve") {
            toast.success(`${action.title}: approved`);
            if (action.kind === "open_link" && typeof res?.result?.url === "string") window.open(res.result.url, "_blank", "noopener,noreferrer");
          }
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    );
  return (
    <li className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center">
      <span className="flex min-w-0 flex-1 items-start gap-3">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-ink-2" aria-hidden />
        <span className="min-w-0">
          <span className="block text-[15px] text-ink">{action.title}</span>
          {action.description && <span className="block text-[13px] text-ink-3">{action.description}</span>}
        </span>
      </span>
      {action.decision ? (
        <ActionResult action={action} />
      ) : expired ? (
        <span className="text-[13px] text-ink-3">Expired</span>
      ) : (
        <span className="flex gap-2">
          <Button size="sm" onClick={() => go("approve")} loading={decide.isPending && decide.variables?.decision === "approve"}>
            Approve
          </Button>
          <Button size="sm" variant="outline" onClick={() => go("reject")} loading={decide.isPending && decide.variables?.decision === "reject"}>
            Dismiss
          </Button>
        </span>
      )}
    </li>
  );
}

/** Full alert: what happened, key details, deadlines, links, evidence, follow-up actions and feedback. */
export function AlertCard({ alert, watchTitle, defaultOpen = false, showWatch = false }: { alert: Alert; watchTitle?: string; defaultOpen?: boolean; showWatch?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const ar = alert.act_result || {};
  const pending = alert.actions.filter((a) => !a.decision).length;
  const relevantTone = alert.my_feedback === false ? "border-l-ok-dot/0" : "";
  return (
    <article className={cn("ticked relative border border-line bg-elevated/70", relevantTone)} aria-labelledby={`alert-${alert.id}`}>
      <span className={cn("absolute inset-y-4 left-0 w-[3px]", alert.my_feedback === false ? "bg-ok-dot" : "bg-amber")} aria-hidden />
      <div className="flex gap-4 p-4 sm:p-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className={cn("h-2.5 w-2.5 rounded-full", alert.my_feedback === false ? "bg-ok-dot" : "bg-amber")} aria-hidden />
            <time dateTime={alert.created_at} className="mono-tight text-[12.5px] text-ink-2" title={formatDateTime(alert.created_at)}>
              {formatDateTime(alert.created_at)}
            </time>
            {showWatch && watchTitle && (
              <Link href={`/watches/${alert.watch_id}`} className="text-[13px] text-ink-3 hover:text-ink hover:underline">
                · {watchTitle}
              </Link>
            )}
            {pending > 0 && <Badge tone="amber">{pending} to approve</Badge>}
            {alert.act_status === "running" && <Badge>Following up…</Badge>}
          </div>
          <h3 id={`alert-${alert.id}`} className="mt-2 font-display text-[23px] leading-tight text-ink">
            <Link href={`/alerts/${alert.id}`} className="hover:underline hover:decoration-1 hover:underline-offset-4">
              {alert.title}
            </Link>
          </h3>
          <p className="mt-1.5 text-[14.5px] leading-relaxed text-ink-2">{ar.what_happened || alert.summary}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <a href={alert.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[13.5px] text-ink underline underline-offset-4">
              <Link2 className="h-3.5 w-3.5" aria-hidden /> View source · {hostOf(alert.source_url)} <ExternalLink className="h-3 w-3" />
            </a>
            <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 text-[13.5px] text-ink-2 hover:text-ink">
              {open ? "Less" : "Details"} <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
            </button>
          </div>
        </div>
        <FeedbackButtons alert={alert} />
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }} className="overflow-hidden">
            <AlertBody alert={alert} />
          </motion.div>
        )}
      </AnimatePresence>
    </article>
  );
}

export function AlertBody({ alert }: { alert: Alert }) {
  const ar = alert.act_result || {};
  const details = keyDetails(alert);
  return (
    <div className="space-y-5 border-t border-line px-4 py-5 sm:px-5">
      {details.length > 0 && (
        <dl className="divide-y divide-line border border-line bg-bg/50">
          {details.map((d) => (
            <div key={d.label} className="flex flex-col gap-0.5 px-4 py-2.5 text-[14px] sm:flex-row sm:gap-4">
              <dt className="w-48 shrink-0 text-ink-2">{d.label}</dt>
              <dd className="min-w-0 break-words font-medium text-ink">
                {isUrl(d.value) ? (
                  <a href={d.value} target="_blank" rel="noopener noreferrer" className="text-info underline underline-offset-4">
                    {hostOf(d.value)}
                  </a>
                ) : (
                  d.value
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {ar.deadlines && ar.deadlines.length > 0 && (
        <div>
          <h4 className="label-mono text-ink-3">Deadlines</h4>
          <ul className="mt-2 flex flex-wrap gap-2">
            {ar.deadlines.map((d) => (
              <li key={d.label + d.date} className="border border-amber/50 bg-amber-soft/50 px-3 py-1.5 text-[13.5px] text-ink">
                {d.label}: <strong className="font-medium">{formatDate(d.date)}</strong> <span className="text-ink-3">({relativeTime(d.date)})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {ar.links && ar.links.length > 0 && (
        <div>
          <h4 className="label-mono text-ink-3">Links</h4>
          <ul className="mt-2 space-y-1.5">
            {ar.links.map((l) => (
              <li key={l.url}>
                <a href={l.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[14px] text-ink underline underline-offset-4">
                  {l.name} <ExternalLink className="h-3 w-3" />
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      {ar.comparison && (
        <div>
          <h4 className="label-mono text-ink-3">Compared with last time</h4>
          <p className="mt-2 text-[14px] text-ink-2">{ar.comparison}</p>
        </div>
      )}
      {ar.checklist && ar.checklist.length > 0 && (
        <div>
          <h4 className="label-mono text-ink-3">Checklist</h4>
          <ul className="mt-2 space-y-1.5">
            {ar.checklist.map((c) => (
              <li key={c} className="flex gap-2 text-[14px] text-ink-2">
                <span className="mt-1.5 h-3 w-3 shrink-0 border border-line-strong" aria-hidden />
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
      {ar.draft_message && (
        <div>
          <h4 className="label-mono text-ink-3">Draft message</h4>
          <pre className="mono-tight mt-2 whitespace-pre-wrap border border-line bg-bg/50 p-3 text-[12.5px] text-ink">{ar.draft_message}</pre>
        </div>
      )}
      {alert.evidence && (
        <figure className="flex gap-3 text-[13.5px] text-ink-2">
          <Quote className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
          <div>
            <blockquote className="italic">“{alert.evidence}”</blockquote>
            <figcaption className="mt-1 text-[12px] text-ink-3">
              Evidence quoted from the page{alert.confidence !== null ? ` · confidence ${Math.round((alert.confidence || 0) * 100)}%` : ""} · decided by{" "}
              {alert.decided_by === "rule" ? "rules" : "AI"}
            </figcaption>
          </div>
        </figure>
      )}
      {alert.actions.length > 0 && (
        <div>
          <h4 className="label-mono flex items-center gap-2 text-ink-3">
            <FileText className="h-3.5 w-3.5" /> Suggested next steps
          </h4>
          <ul className="mt-1 divide-y divide-line">
            {alert.actions.map((a) => (
              <ActionRow key={a.id} alert={alert} action={a} />
            ))}
          </ul>
        </div>
      )}
      {alert.act_status === "failed" && <p className="flex items-center gap-2 text-[13px] text-ink-3"><X className="h-3.5 w-3.5" /> Follow-up work couldn&apos;t finish; the alert itself is complete.</p>}
    </div>
  );
}
