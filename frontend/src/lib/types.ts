// Shapes returned by the Watchtower API (see backend/app/schemas/api.py and docs/API.md).

export type UUID = string;
export type ISODate = string;

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown; request_id?: string };
}

// ------------------------------------------------------------------ account
export type Channel = "email" | "push" | "telegram" | "webhook";
export type DeliveryMode = "instant" | "digest";

export interface Profile {
  id: UUID;
  email: string | null;
  email_verified: boolean;
  display_name: string | null;
  handle: string | null;
  timezone: string;
  locale: string;
  plan_id: string;
  plan_expires_at: ISODate | null;
  role: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  digest_time: string;
  default_channels: Channel[];
  default_delivery_mode: DeliveryMode;
  max_alerts_per_hour: number;
  auto_tune: boolean;
  email_alerts_enabled: boolean;
  marketing_opt_in: boolean;
  created_at: ISODate;
}

export interface PlanLimits {
  max_watches: number;
  max_subscriptions: number;
  min_interval_seconds: number;
  acts_per_month: number;
  intake_per_day: number;
  run_now_per_day: number;
  llm_tokens_per_day: number;
  retention_days: number;
  max_sources_per_watch: number;
  max_alerts_per_hour: number;
  [k: string]: number;
}

export interface PlanFeatures {
  channels: Channel[];
  auto_tune: boolean;
  js_render: boolean;
  api_tokens: boolean;
  webhooks: boolean;
  per_watch_channels: boolean;
  public_watches: boolean;
  [k: string]: unknown;
}

export interface Plan {
  id: "free" | "plus" | "pro" | string;
  name: string;
  price_usd_month: number;
  price_usd_year: number;
  limits: PlanLimits;
  features: PlanFeatures;
}

export interface Usage {
  plan: Plan;
  watches: number;
  subscriptions: number;
  acts_this_month: number;
  intake_today: number;
  run_now_today: number;
  llm_tokens_today: number;
}

export interface ApiToken {
  id: UUID;
  name: string;
  prefix: string;
  created_at: ISODate;
  last_used_at: ISODate | null;
  expires_at: ISODate | null;
  revoked_at: ISODate | null;
}

export interface Delivery {
  id: UUID;
  alert_id: UUID | null;
  channel: Channel;
  kind: string;
  mode: string;
  status: string;
  status_reason: string | null;
  attempts: number;
  created_at: ISODate;
  sent_at: ISODate | null;
}

export interface Channels {
  email: { address: string | null; enabled: boolean; suppressed: boolean; verified: boolean };
  push: { available: boolean; devices: number; vapid_public_key: string | null };
  telegram: { available: boolean; linked: boolean; username: string | null };
  webhook: { available: boolean; endpoints: { id: UUID; url: string; active: boolean; failures: number }[] };
}

// ------------------------------------------------------------------ watches
export type WatchStatus = "draft" | "active" | "paused" | "error" | "completed" | "expired" | "archived";
export type Visibility = "private" | "unlisted" | "public";

export interface Owner {
  handle: string | null;
  display_name: string | null;
  is_community: boolean;
}

export interface Watch {
  id: UUID;
  title: string;
  description: string | null;
  query_text: string;
  category_slug: string | null;
  kind: string;
  tags: string[];
  visibility: Visibility;
  status: WatchStatus;
  status_reason: string | null;
  slug: string;
  subscriber_count: number;
  alert_count: number;
  last_alert_at: ISODate | null;
  moderation_status: string;
  auto_tune: boolean;
  default_delivery_mode: DeliveryMode;
  created_at: ISODate;
  updated_at: ISODate;
  is_owner: boolean;
  is_subscribed: boolean;
  owner: Owner | null;
}

export interface PublicWatch {
  id: UUID;
  title: string;
  description: string | null;
  category_slug: string | null;
  kind: string;
  tags: string[];
  slug: string;
  subscriber_count: number;
  alert_count: number;
  last_alert_at: ISODate | null;
  status: string;
  created_at: ISODate;
  owner: Owner;
}

export interface PublicWatchDetail extends PublicWatch {
  recent_alerts: { id: UUID; title: string; summary: string; source_url: string; created_at: ISODate }[];
  is_owner: boolean;
}

export interface Predicate {
  type: string;
  values?: string[];
  pattern?: string | null;
  threshold?: number | null;
  label?: string | null;
  scope?: "page" | "added" | "new_items";
}

export interface SourceSpec {
  url: string;
  kind?: "page" | "json" | "feed";
  selector?: string | null;
  fetch_mode?: "http" | "render";
  label?: string | null;
}

export interface WatchSpec {
  schema_version?: number;
  kind: string;
  sources: SourceSpec[];
  condition: string;
  predicates: Predicate[];
  predicate_mode: "decide" | "prefilter" | "none";
  keywords: string[];
  extract_fields: string[];
  act: { enabled: boolean; tasks: string[]; instructions?: string | null };
  interval_seconds: number;
  fire_once: boolean;
  expires_at: ISODate | null;
  dedup_window_days: number;
  positive_examples: string[];
  negative_examples: string[];
  notes: string | null;
}

export interface Version {
  id: UUID;
  version: number;
  spec: WatchSpec;
  created_by: string;
  changelog: string | null;
  backtest: Record<string, unknown> | null;
  created_at: ISODate;
}

export type RunOutcome =
  | "baseline"
  | "skipped_unchanged"
  | "no_match"
  | "matched"
  | "duplicate"
  | "deferred"
  | "blocked"
  | "error";

export interface RunStep {
  node: string;
  status: string;
  note?: string | null;
  ms?: number | null;
  at?: ISODate;
}

export interface Run {
  id: UUID;
  trigger: string;
  status: string;
  outcome: RunOutcome | null;
  decided_by: string | null;
  llm_called: boolean;
  llm_tokens: number;
  confidence: number | null;
  reason: string | null;
  diff_summary: string | null;
  error_code: string | null;
  alert_id: UUID | null;
  started_at: ISODate;
  finished_at: ISODate | null;
  duration_ms: number | null;
}

export interface RunDetail extends Run {
  steps: RunStep[];
}

export interface Schedule {
  enabled: boolean;
  interval_seconds: number | null;
  next_run_at: ISODate | null;
  last_run_at: ISODate | null;
  running: boolean;
  consecutive_failures: number;
}

export interface WatchSourceState {
  url: string;
  label: string | null;
  status: string;
  status_reason: string | null;
  last_fetched_at: ISODate | null;
  last_status_code: number | null;
}

export interface Refinement {
  id: UUID;
  rationale: string;
  changes: unknown[];
  backtest: Record<string, unknown>;
  status: string;
  created_at: ISODate;
  proposed_spec: WatchSpec;
}

export interface WatchState {
  watch: Watch;
  current_version: Version | null;
  schedule: Schedule;
  last_run: RunDetail | null;
  last_alert: Alert | null;
  stats: {
    runs_7d: number;
    llm_calls_7d: number;
    skipped_without_ai_7d: number;
    alerts_7d: number;
    errors_7d: number;
    llm_tokens_7d: number;
    ai_skip_ratio_7d: number | null;
  };
  sources: WatchSourceState[];
  pending_refinement: Refinement | null;
  my_subscription: { role: string; delivery_mode: DeliveryMode | null; channels: Channel[]; muted: boolean } | null;
}

export interface DashboardItem {
  watch: Watch;
  schedule: Schedule;
  last_run: {
    outcome: RunOutcome | null;
    decided_by: string | null;
    llm_called: boolean;
    reason: string | null;
    started_at: ISODate;
    status: string;
  } | null;
  alerts_24h: number;
  activity: { runs: number; alerts: number; errors: number }[];
}

export interface Dashboard {
  totals: {
    watches: number;
    active_watches: number;
    checks_today: number;
    alerts_7d: number;
    runs_7d: number;
    ai_skipped_7d: number;
  };
  bucket_hours: number;
  items: DashboardItem[];
}

// ------------------------------------------------------------------ alerts
export interface Action {
  id: UUID;
  kind: string;
  title: string;
  description: string | null;
  payload: Record<string, unknown>;
  owner_only: boolean;
  expires_at: ISODate | null;
  decision: string | null;
  result: Record<string, unknown> | null;
}

export interface ActResult {
  headline?: string;
  what_happened?: string;
  key_details?: Record<string, unknown> | { label: string; value: string }[];
  deadlines?: { label: string; date: string }[];
  links?: { name: string; url: string }[];
  comparison?: string | null;
  checklist?: string[];
  draft_message?: string | null;
  [k: string]: unknown;
}

export interface Alert {
  id: UUID;
  watch_id: UUID;
  title: string;
  summary: string;
  key_facts: Record<string, unknown>;
  evidence: string | null;
  source_url: string;
  confidence: number | null;
  decided_by: string;
  act_status: string;
  act_result: ActResult;
  created_at: ISODate;
  my_feedback: boolean | null;
  actions: Action[];
}

// ------------------------------------------------------------------ intake
export type IntakeStatus =
  | "queued"
  | "running"
  | "awaiting_user"
  | "proposed"
  | "created"
  | "refused"
  | "rejected"
  | "failed"
  | "cancelled";

export interface IntakeQuestion {
  id: string;
  question: string;
  options: string[];
}

export interface IntakeProposal {
  title: string;
  condition: string;
  kind: string;
  category: string;
  sources: { url: string; label: string | null; kind: string }[];
  interval_minutes: number;
  min_interval_minutes: number;
  rules: Predicate[];
  rule_mode: string;
  uses_ai_judgement: boolean;
  fire_once: boolean;
  expires_at: ISODate | null;
  follow_up_tasks: string[];
  extract_fields: string[];
}

export interface IntakeView {
  message?: string;
  questions?: IntakeQuestion[];
  failed_sources?: { url: string; reason: string | null }[];
  proposal?: IntakeProposal;
  dry_run?: { already_met: boolean; reason: string; evidence: string } | null;
  similar_public_watches?: { watch_id: UUID; slug: string; title: string; subscribers: number }[];
  alternatives?: string[];
  reason_code?: string;
  watch_id?: UUID;
  title?: string;
}

export interface IntakeSession {
  id: UUID;
  query: string;
  status: IntakeStatus;
  stage: string | null;
  view: IntakeView;
  rounds: number;
  watch_id: UUID | null;
  created_at: ISODate;
  updated_at: ISODate;
}

// ------------------------------------------------------------------ community
export interface Category {
  slug: string;
  name: string;
  description: string | null;
  icon: string | null;
  watch_count: number;
}

export interface Collection {
  slug: string;
  title: string;
  categories: string[];
  watches: PublicWatch[];
}

export interface ExplorePage {
  items: PublicWatch[];
  next_offset: number | null;
}

// ------------------------------------------------------------------ realtime
export interface StreamEvent<T = Record<string, unknown>> {
  scope: "user" | "watch";
  stream: string;
  type: string;
  at: ISODate;
  data: T;
}
