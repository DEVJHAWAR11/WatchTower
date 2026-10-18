"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";

import { api, newIdempotencyKey } from "./api";
import type {
  Alert,
  ApiToken,
  Category,
  Channels,
  Collection,
  Dashboard,
  Delivery,
  ExplorePage,
  IntakeSession,
  Page,
  Plan,
  Profile,
  Refinement,
  Run,
  RunDetail,
  Usage,
  Version,
  Watch,
  WatchState,
} from "./types";

export const qk = {
  me: ["me"] as const,
  usage: ["me", "usage"] as const,
  dashboard: ["me", "dashboard"] as const,
  myWatches: (role: string) => ["me", "watches", role] as const,
  deliveries: ["me", "deliveries"] as const,
  tokens: ["me", "tokens"] as const,
  channels: ["channels"] as const,
  plans: ["plans"] as const,
  watchState: (id: string) => ["watch", id, "state"] as const,
  watchRuns: (id: string, outcome?: string) => ["watch", id, "runs", outcome || "all"] as const,
  run: (id: string, runId: string) => ["watch", id, "run", runId] as const,
  watchAlerts: (id: string) => ["watch", id, "alerts"] as const,
  versions: (id: string) => ["watch", id, "versions"] as const,
  refinements: (id: string) => ["watch", id, "refinements"] as const,
  alerts: ["alerts"] as const,
  alert: (id: string) => ["alert", id] as const,
  intake: (id: string) => ["intake", id] as const,
  explore: (p: object) => ["explore", p] as const,
  categories: ["explore", "categories"] as const,
  collections: ["explore", "collections"] as const,
};

// ------------------------------------------------------------------ account
export function useMe(enabled = true) {
  return useQuery({ queryKey: qk.me, queryFn: () => api<Profile>("me"), enabled, staleTime: 60_000 });
}
export function useUsage() {
  return useQuery({ queryKey: qk.usage, queryFn: () => api<Usage>("me/usage"), staleTime: 30_000 });
}
export function usePlans() {
  return useQuery({ queryKey: qk.plans, queryFn: () => api<Plan[]>("plans"), staleTime: 10 * 60_000 });
}
export function useDashboard() {
  return useQuery({ queryKey: qk.dashboard, queryFn: () => api<Dashboard>("me/dashboard"), refetchInterval: 60_000 });
}
export function useMyWatches(role: "all" | "owner" | "subscriber" = "all", enabled = true) {
  return useQuery({ queryKey: qk.myWatches(role), queryFn: () => api<Watch[]>("me/watches", { query: { role } }), enabled });
}
export function useDeliveries() {
  return useQuery({ queryKey: qk.deliveries, queryFn: () => api<Delivery[]>("me/deliveries", { query: { limit: 50 } }) });
}
export function useApiTokens(enabled: boolean) {
  return useQuery({ queryKey: qk.tokens, queryFn: () => api<ApiToken[]>("me/api-tokens"), enabled });
}
export function useChannels() {
  return useQuery({ queryKey: qk.channels, queryFn: () => api<Channels>("notifications/channels") });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Profile>("me/settings", { method: "PATCH", body }),
    onSuccess: (p) => qc.setQueryData(qk.me, p),
  });
}

// ------------------------------------------------------------------ watches
export function useWatchState(id: string) {
  return useQuery({
    queryKey: qk.watchState(id),
    queryFn: () => api<WatchState>(`watches/${id}/state`),
    refetchInterval: 90_000,
  });
}

export function useWatchRuns(id: string, outcome?: string, limit = 60) {
  return useInfiniteQuery({
    queryKey: qk.watchRuns(id, outcome),
    queryFn: ({ pageParam }) =>
      api<Page<Run>>(`watches/${id}/runs`, { query: { cursor: pageParam, limit, outcome } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useRunDetail(id: string, runId: string | null) {
  return useQuery({
    queryKey: qk.run(id, runId || ""),
    queryFn: () => api<RunDetail>(`watches/${id}/runs/${runId}`),
    enabled: Boolean(runId),
  });
}

export function useWatchAlerts(id: string) {
  return useInfiniteQuery({
    queryKey: qk.watchAlerts(id),
    queryFn: ({ pageParam }) => api<Page<Alert>>(`watches/${id}/alerts`, { query: { cursor: pageParam, limit: 20 } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useVersions(id: string, enabled: boolean) {
  return useQuery({ queryKey: qk.versions(id), queryFn: () => api<Version[]>(`watches/${id}/versions`), enabled });
}
export function useRefinements(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.refinements(id),
    queryFn: () => api<Refinement[]>(`watches/${id}/refinements`),
    enabled,
  });
}

/** Invalidate everything that depends on a watch after a mutation. */
export function useInvalidateWatch() {
  const qc = useQueryClient();
  return (id: string) => {
    qc.invalidateQueries({ queryKey: ["watch", id] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
}

export function useWatchAction(id: string) {
  const invalidate = useInvalidateWatch();
  return useMutation({
    mutationFn: (v: { path: string; method?: "POST" | "PATCH" | "DELETE" | "PUT"; body?: Record<string, unknown> }) =>
      api<unknown>(`watches/${id}${v.path}`, { method: v.method || "POST", body: v.body }),
    onSuccess: () => invalidate(id),
  });
}

// ------------------------------------------------------------------ alerts
export function useAlerts(watchId?: string) {
  return useInfiniteQuery({
    queryKey: [...qk.alerts, watchId || "all"] as QueryKey,
    queryFn: ({ pageParam }) =>
      api<Page<Alert>>("alerts", { query: { cursor: pageParam, limit: 20, watch_id: watchId } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useAlert(id: string) {
  return useQuery({ queryKey: qk.alert(id), queryFn: () => api<Alert>(`alerts/${id}`) });
}

function patchAlertEverywhere(qc: ReturnType<typeof useQueryClient>, id: string, fn: (a: Alert) => Alert) {
  const patchList = (items: Alert[]) => items.map((a) => (a.id === id ? fn(a) : a));
  // Handles every cached shape that can hold alerts: infinite pages, a single page, a watch state.
  const patch = (data: unknown): unknown => {
    if (!data || typeof data !== "object") return data;
    const d = data as Record<string, unknown>;
    if (Array.isArray(d.pages)) return { ...d, pages: (d.pages as Page<Alert>[]).map((p) => ({ ...p, items: patchList(p.items) })) };
    if (Array.isArray(d.items)) return { ...d, items: patchList(d.items as Alert[]) };
    if ("last_alert" in d && (d.last_alert as Alert | null)?.id === id) return { ...d, last_alert: fn(d.last_alert as Alert) };
    if (d.id === id && "actions" in d) return fn(d as unknown as Alert);
    return data;
  };
  qc.setQueriesData({ queryKey: qk.alerts }, patch);
  qc.setQueriesData({ queryKey: ["alert"] }, patch);
  qc.setQueriesData({ queryKey: ["watch"] }, patch);
}

export function useFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { alertId: string; relevant: boolean; reason?: string }) =>
      api(`alerts/${v.alertId}/feedback`, { body: { relevant: v.relevant, reason: v.reason || null } }),
    onMutate: (v) => {
      const prev = qc.getQueryData<Alert>(qk.alert(v.alertId))?.my_feedback ?? null;
      patchAlertEverywhere(qc, v.alertId, (a) => ({ ...a, my_feedback: v.relevant }));
      return { prev };
    },
    onError: (_e, v, ctx) => patchAlertEverywhere(qc, v.alertId, (a) => ({ ...a, my_feedback: ctx?.prev ?? null })),
  });
}

export function useActionDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { alertId: string; actionId: string; decision: "approve" | "reject" }) =>
      api<{ status: string; result: Record<string, unknown> | null }>(`actions/${v.actionId}/${v.decision}`, { method: "POST" }),
    onSuccess: (res, v) => {
      patchAlertEverywhere(qc, v.alertId, (a) => ({
        ...a,
        actions: a.actions.map((x) => (x.id === v.actionId ? { ...x, decision: res.status, result: res.result ?? null } : x)),
      }));
      qc.invalidateQueries({ queryKey: qk.alert(v.alertId) });
    },
  });
}

// ------------------------------------------------------------------ intake
export function useIntake(id: string | null) {
  return useQuery({
    queryKey: qk.intake(id || ""),
    queryFn: () => api<IntakeSession>(`intake/${id}`),
    enabled: Boolean(id),
    // SSE pushes updates; poll as a safety net while the agent is working.
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "queued" || s === "running" ? 4000 : false;
    },
  });
}

export function useStartIntake() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (query: string) =>
      api<IntakeSession>("intake", { body: { query }, idempotencyKey: newIdempotencyKey() }),
    onSuccess: (s) => qc.setQueryData(qk.intake(s.id), s),
  });
}

export function useIntakeStep(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { step: "answer" | "confirm" | "cancel"; body?: Record<string, unknown> }) =>
      api<IntakeSession>(`intake/${id}/${v.step}`, { method: "POST", body: v.body }),
    onSuccess: (s) => qc.setQueryData(qk.intake(id), s),
  });
}

// ------------------------------------------------------------------ community
export function useExplore(params: { sort: string; category?: string; q?: string }) {
  return useInfiniteQuery({
    queryKey: qk.explore(params),
    queryFn: ({ pageParam }) =>
      api<ExplorePage>("explore", { query: { ...params, limit: 24, offset: pageParam } }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
    staleTime: 30_000,
  });
}
export function useCategories() {
  return useQuery({ queryKey: qk.categories, queryFn: () => api<Category[]>("explore/categories"), staleTime: 5 * 60_000 });
}
export function useCollections() {
  return useQuery({ queryKey: qk.collections, queryFn: () => api<Collection[]>("explore/collections"), staleTime: 60_000 });
}

export function useSubscribe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; subscribe: boolean }) =>
      v.subscribe ? api<Watch>(`watches/${v.id}/subscribe`, { method: "POST", body: {} }) : api(`watches/${v.id}/subscribe`, { method: "DELETE" }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["explore"] });
      qc.invalidateQueries({ queryKey: ["watch", v.id] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
