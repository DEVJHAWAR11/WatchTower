"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Flag, Minus, Plus, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { useWatchMutations } from "@/components/app/watch-menu";
import { ReportDialog } from "@/components/community/public-watch-actions";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/display";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/field";
import { Dialog, DialogContent, Switch } from "@/components/ui/primitives";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCategories, useUsage } from "@/lib/queries";
import type { Channel, WatchSpec, WatchState } from "@/lib/types";
import { cn, formatInterval } from "@/lib/utils";

const INTERVALS = [15, 30, 60, 120, 180, 360, 720, 1440, 4320, 10080];
const TASKS = [
  ["extract_details", "Extract key details"],
  ["deadlines", "Find deadlines"],
  ["compare", "Compare with last time"],
  ["checklist", "Make a checklist"],
  ["draft_message", "Draft a message"],
] as const;

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-5 border-b border-line py-8 first:pt-0 last:border-0 lg:grid-cols-[260px_1fr]">
      <div>
        <h3 className="font-display text-[24px] leading-tight text-ink">{title}</h3>
        {description && <p className="mt-1.5 text-[14px] text-ink-2">{description}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export function WatchSettings({ state }: { state: WatchState }) {
  return state.watch.is_owner ? <OwnerSettings state={state} /> : <SubscriberSettings state={state} />;
}

function OwnerSettings({ state }: { state: WatchState }) {
  const w = state.watch;
  const qc = useQueryClient();
  const router = useRouter();
  const cats = useCategories();
  const usage = useUsage();
  const m = useWatchMutations(w);
  const [title, setTitle] = useState(w.title);
  const [description, setDescription] = useState(w.description || "");
  const [category, setCategory] = useState(w.category_slug || "");
  const [tags, setTags] = useState(w.tags.join(", "));
  const [visibility, setVisibility] = useState(w.visibility);
  const [delivery, setDelivery] = useState(w.default_delivery_mode);
  const [busy, setBusy] = useState<string | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["watch", w.id] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  const patch = async (key: string, body: Record<string, unknown>, ok: string) => {
    setBusy(key);
    try {
      await api(`watches/${w.id}`, { method: "PATCH", body });
      toast.success(ok);
      refresh();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <Section title="Details" description="How this watch appears in your list and, if public, in Community.">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            patch(
              "details",
              {
                title: title.trim(),
                description: description.trim() || null,
                category: category || null,
                tags: tags.split(",").map((t) => t.trim()).filter(Boolean).slice(0, 10),
              },
              "Details saved",
            );
          }}
        >
          <Field label="Title" htmlFor="w-title">
            <Input id="w-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={140} required />
          </Field>
          <Field label="Description" htmlFor="w-desc">
            <Textarea id="w-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} rows={3} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Category" htmlFor="w-cat">
              <NativeSelect id="w-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">None</option>
                {(cats.data ?? []).map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Tags" htmlFor="w-tags" hint="Comma separated, up to 10">
              <Input id="w-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="ssc, results, 2026" />
            </Field>
          </div>
          <Button type="submit" loading={busy === "details"}>
            <Save className="h-4 w-4" /> Save details
          </Button>
        </form>
      </Section>

      <Section title="Visibility" description="Public watches are reviewed, then listed in Community so others can subscribe. One check serves everyone.">
        <div className="space-y-3">
          {(
            [
              ["private", "Private", "Only you can see it."],
              ["unlisted", "Unlisted", "Anyone with the link can view and subscribe."],
              ["public", "Public", "Listed in Community after review."],
            ] as const
          ).map(([v, l, d]) => (
            <label key={v} className={cn("flex cursor-pointer items-start gap-3 border p-4 transition-colors", visibility === v ? "border-ink bg-elevated" : "border-line hover:border-line-strong")}>
              <input type="radio" name="visibility" value={v} checked={visibility === v} onChange={() => setVisibility(v)} className="mt-1 accent-[var(--primary)]" />
              <span>
                <span className="block font-medium text-ink">{l}</span>
                <span className="block text-[14px] text-ink-2">{d}</span>
              </span>
            </label>
          ))}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button onClick={() => patch("vis", { visibility }, visibility === "public" ? "Submitted for review" : "Visibility updated")} loading={busy === "vis"} disabled={visibility === w.visibility}>
              Update visibility
            </Button>
            {w.visibility === "public" && (
              <Badge tone={w.moderation_status === "approved" ? "ok" : w.moderation_status === "rejected" ? "err" : "amber"}>
                Review: {w.moderation_status}
              </Badge>
            )}
          </div>
        </div>
      </Section>

      <Section title="Delivery" description="Default for this watch. Your quiet hours and channels live in Settings.">
        <div className="flex flex-wrap items-center gap-3">
          <NativeSelect aria-label="Delivery mode" value={delivery} onChange={(e) => setDelivery(e.target.value as "instant" | "digest")} className="w-56">
            <option value="instant">Instantly</option>
            <option value="digest">In my daily digest</option>
          </NativeSelect>
          <Button variant="outline" onClick={() => patch("delivery", { default_delivery_mode: delivery }, "Delivery updated")} loading={busy === "delivery"} disabled={delivery === w.default_delivery_mode}>
            Save
          </Button>
        </div>
      </Section>

      {state.current_version && (
        <Section title="What to watch" description="Editing creates a new version. You can always restore an earlier one under Tuning.">
          <SpecEditor watchId={w.id} spec={state.current_version.spec} minIntervalSeconds={usage.data?.plan.limits.min_interval_seconds ?? 900} maxSources={usage.data?.plan.limits.max_sources_per_watch ?? 5} />
        </Section>
      )}

      <Section title="Archive" description="Stops checking and removes it from your list. History is kept for your plan's retention period.">
        <Button variant="danger" onClick={() => setArchiveOpen(true)}>
          Archive this watch
        </Button>
        <Dialog open={archiveOpen} onOpenChange={setArchiveOpen}>
          <DialogContent title="Archive this watch?" description={`“${w.title}” will stop checking.${w.subscriber_count > 1 ? " Others subscribe to it, so make it private first." : ""}`}>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setArchiveOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={async () => {
                  if (await m.archive()) router.push("/dashboard");
                }}
              >
                Archive
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </Section>
    </div>
  );
}

function SpecEditor({ watchId, spec, minIntervalSeconds, maxSources }: { watchId: string; spec: WatchSpec; minIntervalSeconds: number; maxSources: number }) {
  const qc = useQueryClient();
  const [condition, setCondition] = useState(spec.condition);
  const [interval, setInterval] = useState(Math.round(spec.interval_seconds / 60));
  const [sources, setSources] = useState(spec.sources.map((s) => s.url));
  const [keywords, setKeywords] = useState(spec.keywords.join(", "));
  const [fireOnce, setFireOnce] = useState(spec.fire_once);
  const [tasks, setTasks] = useState<string[]>(spec.act?.tasks ?? []);
  const [instructions, setInstructions] = useState(spec.act?.instructions || "");
  const [changelog, setChangelog] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string | null>(null);

  const intervals = useMemo(() => {
    const set = new Set(INTERVALS.filter((m) => m * 60 >= minIntervalSeconds));
    set.add(Math.round(spec.interval_seconds / 60));
    return [...set].sort((a, b) => a - b);
  }, [minIntervalSeconds, spec.interval_seconds]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors(null);
    const urls = sources.map((s) => s.trim()).filter(Boolean);
    if (!urls.length) return setErrors("Add at least one page to watch.");
    const kept = new Map(spec.sources.map((s) => [s.url, s]));
    const next: WatchSpec = {
      ...spec,
      condition: condition.trim(),
      interval_seconds: interval * 60,
      sources: urls.map((u) => kept.get(u) || { url: u }),
      keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean).slice(0, 20),
      fire_once: fireOnce,
      act: { ...spec.act, tasks, instructions: instructions.trim() || null },
    };
    setBusy(true);
    try {
      await api(`watches/${watchId}/spec`, { method: "PUT", body: { spec: next as unknown as Record<string, unknown>, changelog: changelog.trim() || "Edited by owner" } });
      toast.success("Saved as a new version");
      setChangelog("");
      qc.invalidateQueries({ queryKey: ["watch", watchId] });
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.details)) {
        setErrors((err.details as { msg?: string; loc?: unknown[] }[]).map((d) => `${(d.loc || []).slice(-2).join(".")}: ${(d.msg || "").replace("Value error, ", "")}`).join(" · "));
      } else setErrors(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="space-y-5">
      <Field label="Alert me when…" htmlFor="s-cond">
        <Textarea id="s-cond" value={condition} onChange={(e) => setCondition(e.target.value)} minLength={3} maxLength={600} rows={3} required />
      </Field>
      <Field label="Pages to watch" hint={`Up to ${maxSources} on your plan. Public http(s) pages only.`}>
        <ul className="space-y-2">
          {sources.map((s, i) => (
            <li key={i} className="flex gap-2">
              <Input aria-label={`Page ${i + 1}`} type="url" value={s} onChange={(e) => setSources((xs) => xs.map((x, k) => (k === i ? e.target.value : x)))} placeholder="https://…" />
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove page ${i + 1}`} onClick={() => setSources((xs) => xs.filter((_, k) => k !== i))} disabled={sources.length <= 1}>
                <Minus className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
        {sources.length < maxSources && (
          <Button type="button" variant="subtle" size="sm" className="mt-2" onClick={() => setSources((xs) => [...xs, ""])}>
            <Plus className="h-4 w-4" /> Add a page
          </Button>
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Check frequency" htmlFor="s-int">
          <NativeSelect id="s-int" value={interval} onChange={(e) => setInterval(Number(e.target.value))}>
            {intervals.map((m) => (
              <option key={m} value={m}>
                {formatInterval(m * 60)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Helpful keywords" htmlFor="s-kw" hint="Comma separated">
          <Input id="s-kw" value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </Field>
      </div>
      <label className="flex items-center gap-3 text-[14.5px] text-ink-2">
        <Switch checked={fireOnce} onCheckedChange={setFireOnce} label="Stop after the first alert" /> Stop after the first alert
      </label>
      <Field label="When it fires, also…">
        <div className="flex flex-wrap gap-2">
          {TASKS.map(([k, l]) => {
            const on = tasks.includes(k);
            return (
              <button
                type="button"
                key={k}
                aria-pressed={on}
                onClick={() => setTasks((t) => (on ? t.filter((x) => x !== k) : [...t, k]))}
                className={cn("border px-3 py-1.5 text-[13.5px] transition-colors", on ? "border-ink bg-ink text-bg" : "border-line-strong text-ink-2 hover:border-ink")}
              >
                {l}
              </button>
            );
          })}
        </div>
      </Field>
      <Field label="Extra instructions for follow-up (optional)" htmlFor="s-ins">
        <Input id="s-ins" value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={500} placeholder="e.g. list documents I need to apply" />
      </Field>
      <Field label="What changed? (optional)" htmlFor="s-log">
        <Input id="s-log" value={changelog} onChange={(e) => setChangelog(e.target.value)} maxLength={500} placeholder="Shown in version history" />
      </Field>
      {errors && (
        <p className="border border-err/30 bg-err-soft px-3 py-2 text-sm text-err" role="alert">
          {errors}
        </p>
      )}
      <Button type="submit" loading={busy}>
        <Save className="h-4 w-4" /> Save as new version
      </Button>
    </form>
  );
}

function SubscriberSettings({ state }: { state: WatchState }) {
  const w = state.watch;
  const usage = useUsage();
  const m = useWatchMutations(w);
  const router = useRouter();
  const sub = state.my_subscription;
  const [delivery, setDelivery] = useState<"instant" | "digest">(sub?.delivery_mode || w.default_delivery_mode || "instant");
  const [channels, setChannels] = useState<Channel[]>(sub?.channels ?? []);
  const [muted, setMuted] = useState(Boolean(sub?.muted));
  const [busy, setBusy] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const perWatch = Boolean(usage.data?.plan.features.per_watch_channels);
  const allowed = (usage.data?.plan.features.channels ?? ["email", "push", "telegram"]) as Channel[];

  if (!w.is_subscribed)
    return (
      <Card className="p-6 text-ink-2">
        You&apos;re viewing a community watch. Subscribe to choose how you get its alerts.
      </Card>
    );

  const save = async () => {
    setBusy(true);
    try {
      await api(`watches/${w.id}/subscription`, { method: "PATCH", body: { delivery_mode: delivery, muted, ...(perWatch && channels.length ? { channels } : {}) } });
      toast.success("Subscription updated");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Section title="Your subscription" description="These settings only affect you, not other subscribers.">
        <div className="space-y-5">
          <Field label="Delivery" htmlFor="sub-del">
            <NativeSelect id="sub-del" value={delivery} onChange={(e) => setDelivery(e.target.value as "instant" | "digest")} className="sm:w-64">
              <option value="instant">Instantly</option>
              <option value="digest">In my daily digest</option>
            </NativeSelect>
          </Field>
          <Field label="Channels for this watch" hint={perWatch ? "Leave all off to use your defaults." : "Per-watch channels are part of Plus. This watch uses your default channels."}>
            <div className="flex flex-wrap gap-2">
              {allowed.map((c) => {
                const on = channels.includes(c);
                return (
                  <button
                    key={c}
                    type="button"
                    disabled={!perWatch}
                    aria-pressed={on}
                    onClick={() => setChannels((x) => (on ? x.filter((y) => y !== c) : [...x, c]))}
                    className={cn("border px-3 py-1.5 text-[13.5px] capitalize transition-colors disabled:opacity-50", on ? "border-ink bg-ink text-bg" : "border-line-strong text-ink-2 hover:border-ink")}
                  >
                    {c}
                  </button>
                );
              })}
            </div>
          </Field>
          <label className="flex items-center gap-3 text-[14.5px] text-ink-2">
            <Switch checked={muted} onCheckedChange={setMuted} label="Mute this watch" /> Mute (keep it, but send no alerts)
          </label>
          <Button onClick={save} loading={busy}>
            <Save className="h-4 w-4" /> Save
          </Button>
        </div>
      </Section>
      <Section title="Leave or report">
        <div className="flex flex-wrap gap-3">
          <Button
            variant="danger"
            onClick={async () => {
              if (await m.unsubscribe()) router.push("/dashboard");
            }}
          >
            Unsubscribe
          </Button>
          <Dialog open={reportOpen} onOpenChange={setReportOpen}>
            <Button variant="ghost" onClick={() => setReportOpen(true)}>
              <Flag className="h-4 w-4" /> Report this watch
            </Button>
            <ReportDialog watchId={w.id} onDone={() => setReportOpen(false)} />
          </Dialog>
        </div>
      </Section>
    </div>
  );
}
