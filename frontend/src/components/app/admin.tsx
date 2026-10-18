"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, RotateCcw, Search, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState, ErrorState, Skeleton, Sparkbars } from "@/components/ui/display";
import { Field, Input, NativeSelect } from "@/components/ui/field";
import { Dialog, DialogContent, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/queries";
import type { Profile, Watch } from "@/lib/types";
import { formatDateTime, relativeTime } from "@/lib/utils";

import { PageFrame, PageHeader } from "./app-shell";

function useAdmin<T>(path: string, params?: Record<string, string | number | boolean | undefined>, enabled = true) {
  return useQuery({ queryKey: ["admin", path, params], queryFn: () => api<T>(`admin/${path}`, { query: params }), enabled });
}

export function AdminConsole() {
  const me = useMe();
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get("tab") || "system";
  if (me.data && me.data.role !== "admin")
    return (
      <PageFrame>
        <EmptyState icon={<ShieldAlert />} title="Admins only" body="You don't have access to this area." action={<Button asChild><Link href="/dashboard">Back to dashboard</Link></Button>} />
      </PageFrame>
    );
  return (
    <PageFrame>
      <PageHeader kicker="/ Admin" title={<>Control <em className="accent">room.</em></>} subtitle="System health, moderation, users and spend." />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/admin?tab=${t}`, { scroll: false })} className="mt-10">
        <TabsList>
          <TabsTrigger value="system">System</TabsTrigger>
          <TabsTrigger value="moderation">Moderation</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
          <TabsTrigger value="requests">Plan requests</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="domains">Domains</TabsTrigger>
          <TabsTrigger value="spend">AI spend</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>
        <div className="pt-8">
          <TabsContent value="system"><SystemTab /></TabsContent>
          <TabsContent value="moderation"><ModerationTab /></TabsContent>
          <TabsContent value="reports"><ReportsTab /></TabsContent>
          <TabsContent value="requests"><RequestsTab /></TabsContent>
          <TabsContent value="users"><UsersTab /></TabsContent>
          <TabsContent value="domains"><DomainsTab /></TabsContent>
          <TabsContent value="spend"><SpendTab /></TabsContent>
          <TabsContent value="audit"><AuditTab /></TabsContent>
        </div>
      </Tabs>
    </PageFrame>
  );
}

function Loading({ q }: { q: { isPending: boolean; isError: boolean; error: unknown; refetch: () => void } }) {
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return <Skeleton className="h-64 w-full" />;
}

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "err" | "amber" }) {
  return (
    <div className="bg-bg p-4">
      <div className="label-mono text-[10px] text-ink-3">{label}</div>
      <div className={tone === "err" ? "mt-2 font-display text-3xl text-err" : tone === "amber" ? "mt-2 font-display text-3xl text-amber-ink" : "mt-2 font-display text-3xl text-ink"}>{value}</div>
    </div>
  );
}

interface SystemData {
  time: string;
  queues: Record<string, number>;
  scheduler: { overdue_checks: number; max_lag_seconds: number };
  runs_last_hour: { total: number; by_outcome: Record<string, number>; by_decider: Record<string, number>; llm_skip_ratio: number | null };
  totals: Record<string, number>;
  llm_spend_today_usd: number;
  llm_quota: Record<string, { requests_left?: number; tokens_left?: number; blocked_for_s?: number | null }>;
  search_credits: Record<string, { used_this_month: number; monthly_budget: number }>;
}

function SystemTab() {
  const q = useQuery({ queryKey: ["admin", "system"], queryFn: () => api<SystemData>("admin/system"), refetchInterval: 15_000 });
  if (!q.data) return <Loading q={q} />;
  const d = q.data;
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-px border border-line bg-line md:grid-cols-5">
        <Stat label="Active users" value={d.totals.active_users} />
        <Stat label="Active watches" value={d.totals.active_watches} />
        <Stat label="Public watches" value={d.totals.public_watches} />
        <Stat label="Alerts · 24h" value={d.totals.alerts_24h} />
        <Stat label="Failed deliveries · 24h" value={d.totals.failed_deliveries_24h} tone={d.totals.failed_deliveries_24h ? "err" : undefined} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="label-mono text-ink-3">Scheduler & queues</h3>
          <p className="mt-3 text-[15px] text-ink">
            {d.scheduler.overdue_checks} overdue checks · max lag {d.scheduler.max_lag_seconds}s
          </p>
          <ul className="mt-3 grid grid-cols-2 gap-2 text-[14px]">
            {Object.entries(d.queues).map(([k, v]) => (
              <li key={k} className="flex justify-between border-b border-line py-1.5">
                <span className="text-ink-2">{k}</span>
                <span className={v > 100 ? "text-err" : "text-ink"}>{v}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-5">
          <h3 className="label-mono text-ink-3">Checks in the last hour</h3>
          <p className="mt-3 text-[15px] text-ink">
            {d.runs_last_hour.total} runs · {d.runs_last_hour.llm_skip_ratio !== null ? `${Math.round(d.runs_last_hour.llm_skip_ratio * 100)}% without AI` : "no runs"}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(d.runs_last_hour.by_outcome).map(([k, v]) => (
              <Badge key={k}>
                {k}: {v}
              </Badge>
            ))}
          </div>
        </Card>
        <Card className="p-5">
          <h3 className="label-mono text-ink-3">AI quota (Groq)</h3>
          <ul className="mt-3 space-y-2 text-[14px]">
            {Object.entries(d.llm_quota).map(([m, s]) => (
              <li key={m} className="flex flex-wrap justify-between gap-2 border-b border-line py-1.5">
                <span className="mono-tight text-[12px] text-ink">{m}</span>
                <span className="text-ink-2">
                  {s.requests_left ?? "?"} req · {s.tokens_left ?? "?"} tok left
                  {s.blocked_for_s ? <span className="text-err"> · blocked {Math.round(s.blocked_for_s)}s</span> : null}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[13px] text-ink-3">Spend today: ${d.llm_spend_today_usd.toFixed(4)}</p>
        </Card>
        <Card className="p-5">
          <h3 className="label-mono text-ink-3">Search credits this month</h3>
          <ul className="mt-3 space-y-2 text-[14px]">
            {Object.entries(d.search_credits).map(([p, c]) => (
              <li key={p} className="flex justify-between border-b border-line py-1.5">
                <span className="capitalize text-ink">{p}</span>
                <span className="text-ink-2">
                  {c.used_this_month} / {c.monthly_budget}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <p className="text-[12.5px] text-ink-3">Updated {relativeTime(d.time)} · refreshes every 15s</p>
    </div>
  );
}

function useAdminAction() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    try {
      await fn();
      toast.success(ok);
      qc.invalidateQueries({ queryKey: ["admin"] });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  return { busy, run };
}

function ModerationTab() {
  const q = useAdmin<Watch[]>("moderation");
  const { busy, run } = useAdminAction();
  if (!q.data) return <Loading q={q} />;
  if (!q.data.length) return <EmptyState title="Queue is empty" body="New public watches appear here when the AI isn't sure." />;
  return (
    <ul className="divide-y divide-line border-y border-line">
      {q.data.map((w) => (
        <li key={w.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <Link href={`/watches/${w.id}`} className="font-medium text-ink underline underline-offset-4">
              {w.title}
            </Link>
            <p className="text-[14px] text-ink-2">{w.description || w.query_text}</p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => run(`a${w.id}`, () => api(`admin/watches/${w.id}/moderation`, { body: { decision: "approve", reason: "Approved by admin" } }), "Approved")} loading={busy === `a${w.id}`}>
              <Check className="h-4 w-4" /> Approve
            </Button>
            <Button size="sm" variant="danger" onClick={() => run(`r${w.id}`, () => api(`admin/watches/${w.id}/moderation`, { body: { decision: "reject", reason: "Rejected by admin" } }), "Rejected")} loading={busy === `r${w.id}`}>
              <X className="h-4 w-4" /> Reject
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function ReportsTab() {
  const q = useAdmin<{ id: string; watch_id: string; reason: string; detail: string | null; created_at: string }[]>("reports");
  const { busy, run } = useAdminAction();
  if (!q.data) return <Loading q={q} />;
  if (!q.data.length) return <EmptyState title="No open reports" body="Reported community watches show up here." />;
  return (
    <ul className="divide-y divide-line border-y border-line">
      {q.data.map((r) => (
        <li key={r.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Badge tone="err">{r.reason}</Badge>
              <span className="text-[13px] text-ink-3">{relativeTime(r.created_at)}</span>
            </div>
            {r.detail && <p className="mt-1 text-[14px] text-ink-2">{r.detail}</p>}
            <Link href={`/watches/${r.watch_id}`} className="text-[14px] text-ink underline underline-offset-4">
              Open watch
            </Link>
          </div>
          <Button size="sm" variant="danger" onClick={() => run(r.id, () => api(`admin/watches/${r.watch_id}/disable`, { method: "POST", query: { reason: `Report: ${r.reason}` } }), "Watch disabled")} loading={busy === r.id}>
            <Ban className="h-4 w-4" /> Disable watch
          </Button>
        </li>
      ))}
    </ul>
  );
}

interface AuditRow {
  id: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

function RequestsTab() {
  const q = useAdmin<AuditRow[]>("audit", { action: "plan.request", limit: 100 });
  const { busy, run } = useAdminAction();
  if (!q.data) return <Loading q={q} />;
  if (!q.data.length) return <EmptyState title="No plan requests" body="When users ask to upgrade, their requests appear here." />;
  return (
    <ul className="divide-y divide-line border-y border-line">
      {q.data.map((r) => {
        const plan = String(r.meta.plan_id || "");
        return (
          <li key={r.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1 text-[14px]">
              <p className="text-ink">
                <code className="mono-tight text-[12px]">{r.actor_id}</code> wants <Badge tone="amber">{plan}</Badge> (from {String(r.meta.from || "?")})
              </p>
              {r.meta.note ? <p className="mt-1 text-ink-2">“{String(r.meta.note)}”</p> : null}
              <p className="text-[12.5px] text-ink-3">{formatDateTime(r.created_at)}</p>
            </div>
            {r.actor_id && (
              <Button size="sm" onClick={() => run(r.id, () => api(`admin/users/${r.actor_id}/plan`, { body: { plan_id: plan, reason: "Plan request" } }), `Switched to ${plan}`)} loading={busy === r.id}>
                Apply {plan}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function UsersTab() {
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  const q = useAdmin<Profile[]>("users", { q: query || undefined, limit: 50 });
  const { busy, run } = useAdminAction();
  const [planFor, setPlanFor] = useState<Profile | null>(null);
  const [plan, setPlan] = useState("plus");
  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(term.trim());
        }}
        className="flex max-w-lg gap-2"
      >
        <Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Search email or handle" aria-label="Search users" />
        <Button type="submit" variant="outline">
          <Search className="h-4 w-4" /> Search
        </Button>
      </form>
      <div className="mt-6">
        {!q.data ? (
          <Loading q={q} />
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {q.data.map((u) => (
              <li key={u.id} className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1 text-[14px]">
                  <p className="text-ink">
                    {u.display_name || u.handle || "—"} <span className="text-ink-3">· {u.email}</span>
                  </p>
                  <p className="text-[12.5px] text-ink-3">
                    Joined {formatDateTime(u.created_at)} · {u.role}
                  </p>
                </div>
                <Badge tone={u.plan_id === "free" ? "neutral" : "amber"}>{u.plan_id}</Badge>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => { setPlanFor(u); setPlan(u.plan_id === "free" ? "plus" : u.plan_id); }}>
                    Change plan
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => run(u.id, () => api(`admin/users/${u.id}/suspend`, { body: { suspend: true, reason: "Suspended by admin" } }), "User suspended")} loading={busy === u.id}>
                    Suspend
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Dialog open={Boolean(planFor)} onOpenChange={(o) => !o && setPlanFor(null)}>
        <DialogContent title="Change plan" description={planFor?.email || undefined}>
          <div className="space-y-4">
            <Field label="Plan" htmlFor="adm-plan">
              <NativeSelect id="adm-plan" value={plan} onChange={(e) => setPlan(e.target.value)}>
                <option value="free">Free</option>
                <option value="plus">Plus</option>
                <option value="pro">Pro</option>
              </NativeSelect>
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setPlanFor(null)}>
                Cancel
              </Button>
              <Button
                onClick={async () => {
                  if (!planFor) return;
                  await run(`p${planFor.id}`, () => api(`admin/users/${planFor.id}/plan`, { body: { plan_id: plan, reason: "Changed by admin" } }), "Plan changed");
                  setPlanFor(null);
                }}
                loading={busy === `p${planFor?.id}`}
              >
                Apply
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DomainsTab() {
  const [blockedOnly, setBlockedOnly] = useState(true);
  const q = useAdmin<{ domain: string; denylisted: boolean; blocked_until: string | null; block_reason: string | null; block_count: number; needs_render: boolean }[]>("domains", { blocked_only: blockedOnly });
  const { busy, run } = useAdminAction();
  return (
    <div>
      <label className="flex items-center gap-2 text-[14px] text-ink-2">
        <input type="checkbox" checked={blockedOnly} onChange={(e) => setBlockedOnly(e.target.checked)} className="accent-[var(--primary)]" /> Only blocked or denylisted
      </label>
      <div className="mt-5">
        {!q.data ? (
          <Loading q={q} />
        ) : q.data.length === 0 ? (
          <EmptyState title="All clear" body="No domains are blocking us right now." />
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {q.data.map((d) => (
              <li key={d.domain} className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1 text-[14px]">
                  <p className="font-medium text-ink">{d.domain}</p>
                  <p className="text-[12.5px] text-ink-3">
                    {d.denylisted ? "Denylisted · " : ""}
                    {d.blocked_until ? `Blocked until ${formatDateTime(d.blocked_until)} · ` : ""}
                    {d.block_reason || ""} {d.block_count ? `· ${d.block_count} blocks` : ""} {d.needs_render ? "· JS render" : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  {d.blocked_until && (
                    <Button size="sm" variant="outline" onClick={() => run(d.domain, () => api(`admin/domains/${encodeURIComponent(d.domain)}`, { method: "PUT", body: { clear_block: true } }), "Block cleared")} loading={busy === d.domain}>
                      <RotateCcw className="h-4 w-4" /> Clear block
                    </Button>
                  )}
                  <Button size="sm" variant={d.denylisted ? "outline" : "danger"} onClick={() => run(`d${d.domain}`, () => api(`admin/domains/${encodeURIComponent(d.domain)}`, { method: "PUT", body: { denylisted: !d.denylisted } }), d.denylisted ? "Removed from denylist" : "Denylisted")} loading={busy === `d${d.domain}`}>
                    {d.denylisted ? "Allow" : "Denylist"}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function SpendTab() {
  const q = useAdmin<{ by_day_usd: Record<string, number>; rows: { day: string; model: string; purpose: string; calls: number; cache_hits: number; prompt_tokens: number; completion_tokens: number; cost_usd: number; errors: number }[] }>("spend", { days: 14 });
  if (!q.data) return <Loading q={q} />;
  const days = Object.entries(q.data.by_day_usd).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="space-y-6">
      <Card className="p-5">
        <h3 className="label-mono text-ink-3">Cost per day (USD), last 14 days</h3>
        {days.length ? (
          <div className="mt-4 flex items-end gap-6">
            <Sparkbars values={days.map(([, v]) => Math.round(v * 10000))} tone="amber" height={60} className="w-auto" />
            <p className="font-display text-3xl text-ink">${days.reduce((s, [, v]) => s + v, 0).toFixed(3)}</p>
          </div>
        ) : (
          <p className="mt-3 text-ink-2">No AI usage recorded yet.</p>
        )}
      </Card>
      {q.data.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[13.5px]">
            <thead className="label-mono text-[10px] text-ink-3">
              <tr className="border-b border-line">
                {["Day", "Model", "Purpose", "Calls", "Cache hits", "Tokens", "Errors", "Cost"].map((h) => (
                  <th key={h} className="py-3 pr-4 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r, i) => (
                <tr key={i} className="border-b border-line">
                  <td className="py-2.5 pr-4 text-ink">{r.day}</td>
                  <td className="mono-tight py-2.5 pr-4 text-[11.5px] text-ink-2">{r.model}</td>
                  <td className="py-2.5 pr-4 text-ink-2">{r.purpose}</td>
                  <td className="py-2.5 pr-4 text-ink">{r.calls}</td>
                  <td className="py-2.5 pr-4 text-ink-2">{r.cache_hits}</td>
                  <td className="py-2.5 pr-4 text-ink-2">{(r.prompt_tokens + r.completion_tokens).toLocaleString("en-IN")}</td>
                  <td className={r.errors ? "py-2.5 pr-4 text-err" : "py-2.5 pr-4 text-ink-3"}>{r.errors}</td>
                  <td className="py-2.5 pr-4 text-ink">${r.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AuditTab() {
  const [action, setAction] = useState("");
  const q = useAdmin<AuditRow[]>("audit", { action: action || undefined, limit: 200 });
  return (
    <div>
      <div className="max-w-sm">
        <Input value={action} onChange={(e) => setAction(e.target.value.trim())} placeholder="Filter by action, e.g. watch.archive" aria-label="Filter by action" />
      </div>
      <div className="mt-5">
        {!q.data ? (
          <Loading q={q} />
        ) : q.data.length === 0 ? (
          <EmptyState title="Nothing logged" body={action ? "No entries for that action." : "Audit entries appear as people use the app."} />
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {q.data.map((a) => (
              <li key={a.id} className="grid gap-1 py-3 text-[13.5px] sm:grid-cols-[180px_200px_1fr]">
                <span className="text-ink-3">{formatDateTime(a.created_at)}</span>
                <span className="font-medium text-ink">{a.action}</span>
                <span className="mono-tight min-w-0 truncate text-[11.5px] text-ink-2">
                  {a.target_type ? `${a.target_type}:${a.target_id}` : ""} {Object.keys(a.meta || {}).length ? JSON.stringify(a.meta) : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {q.error instanceof ApiError && <p className="mt-3 text-sm text-err">{q.error.message}</p>}
    </div>
  );
}
