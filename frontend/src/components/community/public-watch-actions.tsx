"use client";

import { Flag, GitFork, Radio } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { Field, NativeSelect, Textarea } from "@/components/ui/field";
import { api, errorMessage } from "@/lib/api";
import { useMyWatches } from "@/lib/queries";
import type { Watch } from "@/lib/types";
import { useSignedIn } from "@/lib/use-session";

import { SubscribeButton } from "./watch-card";

export function PublicWatchActions({ watch }: { watch: { id: string; slug: string; title: string; is_owner?: boolean } }) {
  const signedIn = useSignedIn();
  const mine = useMyWatches("all", Boolean(signedIn));
  const subscribed = Boolean(mine.data?.some((w) => w.id === watch.id));
  const isOwner = Boolean(mine.data?.some((w) => w.id === watch.id && w.is_owner));
  const router = useRouter();
  const [forking, setForking] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);

  const fork = async () => {
    if (!signedIn) return router.push(`/signup?next=${encodeURIComponent(`/explore/${watch.slug}`)}`);
    setForking(true);
    try {
      const w = await api<Watch>(`watches/${watch.id}/fork`, { method: "POST" });
      toast.success("Copied to your watches", { description: "Customise it however you like." });
      router.push(`/watches/${w.id}`);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setForking(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      {!isOwner && <SubscribeButton watch={watch} subscribed={subscribed} size="md" />}
      {signedIn && (
        <Button asChild variant="outline" mono>
          <Link href={`/watches/${watch.id}`}>
            <Radio className="h-4 w-4" /> Open live view
          </Link>
        </Button>
      )}
      {!isOwner && (
        <Button variant="ghost" mono onClick={fork} loading={forking}>
          <GitFork className="h-4 w-4" /> Fork & customise
        </Button>
      )}
      {signedIn && !isOwner && (
        <Dialog open={reportOpen} onOpenChange={setReportOpen}>
          <Button variant="ghost" mono onClick={() => setReportOpen(true)} className="text-ink-3">
            <Flag className="h-4 w-4" /> Report
          </Button>
          <ReportDialog watchId={watch.id} onDone={() => setReportOpen(false)} />
        </Dialog>
      )}
    </div>
  );
}

const REASONS = [
  { v: "spam", label: "Spam or advertising" },
  { v: "scam", label: "Scam or fake opportunity" },
  { v: "harmful", label: "Harmful or abusive" },
  { v: "privacy", label: "Targets a private person" },
  { v: "broken", label: "Broken or never works" },
  { v: "other", label: "Something else" },
];

export function ReportDialog({ watchId, onDone }: { watchId: string; onDone: () => void }) {
  const [reason, setReason] = useState("spam");
  const [detail, setDetail] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`watches/${watchId}/report`, { body: { reason, detail: detail.trim() || null } });
      toast.success("Thanks, we'll review it.");
      onDone();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <DialogContent title="Report this watch" description="Reports are reviewed by moderators. Watches with several reports are hidden automatically.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Reason" htmlFor="report-reason">
          <NativeSelect id="report-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => (
              <option key={r.v} value={r.v}>
                {r.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Details (optional)" htmlFor="report-detail">
          <Textarea id="report-detail" maxLength={1000} value={detail} onChange={(e) => setDetail(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Send report
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
