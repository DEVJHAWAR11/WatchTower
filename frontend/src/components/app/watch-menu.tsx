"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Archive, BellOff, ExternalLink, MoreVertical, Pause, Play, RefreshCw, UserMinus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/primitives";
import { ApiError, api, errorMessage } from "@/lib/api";
import type { Watch } from "@/lib/types";

export function useWatchMutations(watch: Pick<Watch, "id" | "title" | "status">) {
  const qc = useQueryClient();
  const router = useRouter();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["watch", watch.id] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      refresh();
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.isQuota) {
        toast.error("Plan limit reached", { description: e.message, action: { label: "See plans", onClick: () => router.push("/settings?tab=plan") } });
      } else toast.error(errorMessage(e));
      return false;
    }
  };
  return {
    checkNow: () => run(() => api(`watches/${watch.id}/run`, { method: "POST" }), "Checking now. Follow it in the live view."),
    pause: () => run(() => api(`watches/${watch.id}/pause`, { method: "POST" }), "Watch paused"),
    resume: () => run(() => api(`watches/${watch.id}/resume`, { method: "POST" }), "Watch resumed"),
    archive: () => run(() => api(`watches/${watch.id}`, { method: "DELETE" }), "Watch archived"),
    unsubscribe: () => run(() => api(`watches/${watch.id}/subscribe`, { method: "DELETE" }), "Unsubscribed"),
    mute: (muted: boolean) =>
      run(() => api(`watches/${watch.id}/subscription`, { method: "PATCH", body: { muted } }), muted ? "Muted: no alerts from this watch" : "Unmuted"),
  };
}

export function WatchRowMenu({ watch, onOpen }: { watch: Watch; onOpen: () => void }) {
  const m = useWatchMutations(watch);
  const [confirm, setConfirm] = useState<null | "archive" | "unsubscribe">(null);
  const [busy, setBusy] = useState(false);
  const canRun = watch.is_owner && (watch.status === "active" || watch.status === "error");
  const act = async () => {
    setBusy(true);
    const ok = confirm === "archive" ? await m.archive() : await m.unsubscribe();
    setBusy(false);
    if (ok) setConfirm(null);
  };

  return (
    <>
      <Menu>
        <MenuTrigger
          className="grid h-9 w-9 place-items-center rounded-[3px] text-ink-2 hover:bg-sunken hover:text-ink"
          aria-label={`Actions for ${watch.title}`}
          onClick={(e) => e.stopPropagation()}
        >
          <MoreVertical className="h-[18px] w-[18px]" />
        </MenuTrigger>
        <MenuContent>
          <MenuItem icon={<ExternalLink />} onSelect={onOpen}>
            Open live view
          </MenuItem>
          {watch.is_owner ? (
            <>
              <MenuItem icon={<RefreshCw />} onSelect={() => m.checkNow()} disabled={!canRun}>
                Check now
              </MenuItem>
              {watch.status === "paused" || watch.status === "completed" || watch.status === "expired" ? (
                <MenuItem icon={<Play />} onSelect={() => m.resume()}>
                  Resume
                </MenuItem>
              ) : (
                <MenuItem icon={<Pause />} onSelect={() => m.pause()} disabled={!(watch.status === "active" || watch.status === "error")}>
                  Pause
                </MenuItem>
              )}
              <MenuSeparator />
              <MenuItem icon={<Archive />} danger onSelect={() => setConfirm("archive")}>
                Archive
              </MenuItem>
            </>
          ) : (
            <>
              <MenuItem icon={<BellOff />} onSelect={() => m.mute(true)}>
                Mute alerts
              </MenuItem>
              <MenuSeparator />
              <MenuItem icon={<UserMinus />} danger onSelect={() => setConfirm("unsubscribe")}>
                Unsubscribe
              </MenuItem>
            </>
          )}
        </MenuContent>
      </Menu>
      <Dialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)}>
        <DialogContent
          title={confirm === "archive" ? "Archive this watch?" : "Unsubscribe?"}
          description={
            confirm === "archive"
              ? `“${watch.title}” stops checking and moves out of your list. Its history is kept for your plan's retention period.`
              : `You'll stop getting alerts from “${watch.title}”. You can subscribe again any time.`
          }
        >
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={act} loading={busy}>
              {confirm === "archive" ? "Archive watch" : "Unsubscribe"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
