"use client";

/**
 * One Server-Sent Events connection per tab: the user's own stream plus any watches currently on screen.
 * Pages call `useWatchStream(id)` to add a watch; the provider reconnects and resumes from the last event id
 * (and replays the last few hours of that watch's events so the live log has history).
 */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { qk } from "./queries";
import type { IntakeSession, StreamEvent } from "./types";

const EVENT_TYPES = [
  "ready",
  "intake.updated",
  "run.started",
  "run.step",
  "run.completed",
  "watch.scheduled",
  "act.started",
  "act.completed",
  "watch.refined",
  "feedback.recorded",
  "alert.created",
  "delivery.sent",
  "notification",
  "refinement.proposed",
] as const;

const REPLAY_MS = 6 * 3600 * 1000;

export type LiveEvent = StreamEvent & { id: string };
type Listener = (e: LiveEvent) => void;
export type StreamStatus = "connecting" | "live" | "offline";

interface Ctx {
  status: StreamStatus;
  subscribe: (fn: Listener) => () => void;
  addWatch: (id: string) => () => void;
}

const StreamContext = createContext<Ctx | null>(null);

function decodePos(id: string | null): Record<string, string> {
  if (!id) return {};
  try {
    const b64 = id.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (id.length % 4)) % 4);
    return JSON.parse(atob(b64));
  } catch {
    return {};
  }
}

function encodePos(pos: Record<string, string>): string {
  return btoa(JSON.stringify(pos)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function StreamProvider({ children, enabled = true }: { children: React.ReactNode; enabled?: boolean }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [watchCounts, setWatchCounts] = useState<Record<string, number>>({});
  const listeners = useRef(new Set<Listener>());
  const lastId = useRef<string | null>(null);
  // Bumped to force a reconnect after the browser gave up (EventSource doesn't retry non-200 responses).
  const [attempt, setAttempt] = useState(0);
  const backoff = useRef(0);
  const watchIds = useMemo(
    () => Object.keys(watchCounts).filter((k) => watchCounts[k] > 0).sort().slice(0, 5),
    [watchCounts],
  );

  const handleGlobal = useCallback(
    (e: LiveEvent) => {
      const d = e.data as Record<string, unknown>;
      switch (e.type) {
        case "intake.updated": {
          const sid = String(d.session_id || "");
          if (sid) {
            qc.setQueryData<IntakeSession>(qk.intake(sid), (old) =>
              old
                ? { ...old, status: d.status as IntakeSession["status"], stage: (d.stage as string) ?? old.stage, view: (d.view as IntakeSession["view"]) ?? old.view }
                : old,
            );
            if (d.status === "created") qc.invalidateQueries({ queryKey: ["me"] });
          }
          break;
        }
        case "alert.created": {
          qc.invalidateQueries({ queryKey: qk.alerts });
          qc.invalidateQueries({ queryKey: qk.dashboard });
          const title = String(d.title || "New alert");
          if (!d.held) {
            toast(title, {
              description: d.mode === "digest" ? "Added to your digest" : "Your watch fired.",
              action: d.alert_id ? { label: "Open", onClick: () => router.push(`/alerts/${d.alert_id}`) } : undefined,
            });
          }
          break;
        }
        case "run.completed":
        case "watch.scheduled":
        case "watch.refined":
        case "act.completed": {
          const wid = e.stream;
          if (e.scope === "watch") {
            qc.invalidateQueries({ queryKey: ["watch", wid, "state"] });
            if (e.type === "run.completed") qc.invalidateQueries({ queryKey: ["watch", wid, "runs"] });
            if (e.type === "act.completed" || (e.type === "run.completed" && d.alert_id)) {
              qc.invalidateQueries({ queryKey: ["watch", wid, "alerts"] });
              qc.invalidateQueries({ queryKey: qk.alerts });
            }
            if (e.type === "watch.refined") qc.invalidateQueries({ queryKey: ["watch", wid, "versions"] });
          }
          qc.invalidateQueries({ queryKey: qk.dashboard });
          break;
        }
        case "notification": {
          const title = String(d.title || "Watchtower");
          toast(title, { description: d.body ? String(d.body) : undefined });
          qc.invalidateQueries({ queryKey: ["me"] });
          break;
        }
        case "refinement.proposed": {
          toast("A watch can be improved", { description: "Review the suggested change on the watch page." });
          qc.invalidateQueries({ queryKey: ["watch"] });
          break;
        }
      }
    },
    [qc, router],
  );

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const pos = decodePos(lastId.current);
    const replayFrom = `${Date.now() - REPLAY_MS}-0`;
    for (const w of watchIds) if (!pos[`ev:watch:${w}`]) pos[`ev:watch:${w}`] = replayFrom;
    const params = new URLSearchParams();
    watchIds.forEach((w) => params.append("watch", w));
    if (Object.keys(pos).length) params.set("since", encodePos(pos));
    const es = new EventSource(`/v1/stream?${params.toString()}`);
    let failures = 0;

    const onMessage = (msg: MessageEvent) => {
      if (msg.lastEventId) lastId.current = msg.lastEventId;
      if (msg.type === "ready") {
        failures = 0;
        setStatus("live");
        backoff.current = 0;
        return;
      }
      let payload: StreamEvent;
      try {
        payload = JSON.parse(msg.data);
      } catch {
        return;
      }
      const ev: LiveEvent = { ...payload, type: payload.type || msg.type, id: msg.lastEventId || `${Date.now()}` };
      handleGlobal(ev);
      listeners.current.forEach((fn) => fn(ev));
    };
    EVENT_TYPES.forEach((t) => es.addEventListener(t, onMessage as EventListener));
    let retry: ReturnType<typeof setTimeout> | undefined;
    es.onerror = () => {
      failures += 1;
      if (es.readyState === EventSource.CLOSED) {
        setStatus("offline");
        // Back off 3s, 6s, 12s … up to 60s, then try again with a fresh connection.
        const delay = Math.min(60_000, 3000 * 2 ** Math.min(backoff.current++, 5));
        retry = setTimeout(() => setAttempt((a) => a + 1), delay);
      } else {
        setStatus(failures > 2 ? "offline" : "connecting");
      }
    };
    const onOnline = () => es.readyState === EventSource.CLOSED && setAttempt((a) => a + 1);
    window.addEventListener("online", onOnline);
    return () => {
      clearTimeout(retry);
      window.removeEventListener("online", onOnline);
      EVENT_TYPES.forEach((t) => es.removeEventListener(t, onMessage as EventListener));
      es.close();
    };
  }, [enabled, watchIds, handleGlobal, attempt]);

  const subscribe = useCallback((fn: Listener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  const addWatch = useCallback((id: string) => {
    setWatchCounts((c) => ({ ...c, [id]: (c[id] || 0) + 1 }));
    return () => setWatchCounts((c) => ({ ...c, [id]: Math.max(0, (c[id] || 1) - 1) }));
  }, []);

  const value = useMemo(() => ({ status, subscribe, addWatch }), [status, subscribe, addWatch]);
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
}

export function useStream() {
  return useContext(StreamContext);
}

/** Keep a watch's events flowing while the component is mounted; `onEvent` receives every event. */
export function useWatchStream(watchId: string | null, onEvent?: Listener) {
  const ctx = useContext(StreamContext);
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);
  useEffect(() => {
    if (!ctx || !watchId) return;
    const off = ctx.addWatch(watchId);
    const unsub = ctx.subscribe((e) => handler.current?.(e));
    return () => {
      off();
      unsub();
    };
  }, [ctx, watchId]);
  return ctx?.status ?? "offline";
}

/** Subscribe to every event (e.g. intake progress) without adding watches. */
export function useStreamEvents(onEvent: Listener) {
  const ctx = useContext(StreamContext);
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);
  useEffect(() => {
    if (!ctx) return;
    return ctx.subscribe((e) => handler.current(e));
  }, [ctx]);
}
