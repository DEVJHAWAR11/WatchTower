# Watchtower: architecture

Watchtower lets people describe, in plain language, something on the public web to keep an eye on. AI agents
turn that into a **watch**, check the web on a schedule, decide whether the condition is really met, do the
follow-up work, and send **one** complete notification. Watches can be shared with the community, so one check
serves every subscriber.

## Processes

```
             ┌──────────── Supabase Auth (identity, JWT, OAuth) ───────────┐
             │                                                             │
Frontend ──► API (FastAPI, stateless, N replicas) ──► Postgres (Supabase)  │
   ▲  SSE      │  REST /v1/*, SSE /v1/stream          ▲   source of truth  │
   │           │                                      │                    │
   │           ▼                                      │                    │
   └── Redis ◄─┴── streams (realtime), queues (arq), caches, rate limits, locks
                    ▲                ▲
         Scheduler (N replicas)   Workers (N replicas, per-queue concurrency)
         claims due checks          checks │ agents (intake/act/refine/moderation) │ notify │ maintenance (cron)
         FOR UPDATE SKIP LOCKED              │
                                             ├─► the web (SSRF-safe fetcher, robots.txt, per-domain politeness)
                                             ├─► Groq (LLM ladder) · Tavily / Brave (search)
                                             └─► Resend/SMTP · Web Push · Telegram · signed webhooks
```

| Process | Entry point | Scales by |
|---|---|---|
| API | `uvicorn app.main:app` | replicas behind a load balancer (stateless) |
| Scheduler | `python -m app.workers.scheduler` | replicas (SKIP LOCKED + leases, no leader needed) |
| Workers | `python -m app.workers.main --queues checks,agents,notify,maintenance` | replicas; split queues per deployment |
| Migrations | `alembic upgrade head` | once per deploy |

Postgres is the source of truth for everything durable. Redis only holds queues, caches, realtime streams and
rate-limit state, so a Redis flush loses no data: the scheduler re-claims checks when leases expire, and the
maintenance sweeper re-drives any alert whose follow-up or notification job was lost.

## Data model (key tables)

- `profiles`: one per Supabase user (`id = auth.users.id`), with settings, plan, timezone, quiet hours and digest time.
- `plans`: limits and features stored as data (free / plus / pro). `usage_counters` hold atomic per-period quotas.
- `watches` (intent, visibility, status) → `watch_versions` (immutable compiled **WatchSpec**, changelog, backtest).
- `checks`: a narrow scheduling table (`next_run_at`, lease, backoff) that the scheduler scans constantly.
- `sources` + `source_snapshots`: canonical URLs **shared across all watches** pointing at them.
- `watch_source_state`: what *this* watch last saw on a source (its own view after selectors/normalisation).
- `runs`: every check, with outcome, `decided_by` (hash / noise / rule / triage / llm / cache), reason, LLM
  tokens/cost and a per-node `steps` trace. This is what the live view shows.
- `alerts` are unique per (watch, fingerprint). `alert_deliveries` are unique per (dedup_key, channel), so a
  delivery can never be sent twice.
- `proposed_actions` + `action_decisions` (per-user approvals), `reminders`, `feedback`, `refinement_proposals`.
- `intake_sessions` mirror the LangGraph intake threads (graph state lives in the LangGraph Postgres checkpointer).

RLS is enabled on every table with no policies. Supabase's `anon` and `authenticated` roles therefore can't read
anything through PostgREST: the API is the only way in, and it enforces authorisation itself.

## Agents (LangGraph)

### Intake: plain language → tested watch (`app/agents/intake.py`)
`screen → analyze → [clarify ⟲] → discover → validate → [need_url ⟲] → compile → dry_run → propose ⟲ → create`

- A deterministic pre-screen refuses obvious abuse (stalking, doxxing, hacking) before any LLM call. It is tested
  against benign look-alikes.
- One smart-model call does safety, feasibility (vague / impossible / contradictory / past / not observable /
  needs login / too broad), the precise condition, deterministic predicates, search queries, extract fields and
  interval.
- Source discovery checks user URLs first, then a curated India source registry (SSC, UPSC, NTA, state PSCs, NSP,
  NSE/BSE…), then ATS feeds (Greenhouse/Lever/Ashby) and GitHub release feeds, then Tavily/Brave search. Every
  candidate is fetched through the SSRF-safe client, and a fast model ranks them.
- The dry run tells the user if the condition is *already* true right now.
- `interrupt()` pauses for questions, missing URLs, and the final confirm/edit. Threads are checkpointed in Postgres.
- On create, the current page is stored as the baseline, so the first scheduled run only reacts to new changes.

### Evaluation: every scheduled check (`app/agents/evaluate.py`)
`fetch → change_gate → [rules] → [triage] → judge → dedup → fire`, with a cost ladder that stops as early as possible:

| Step | Cost | Decides when |
|---|---|---|
| Shared fetch | network (or reuse within freshness window) | source blocked/gone → error/backoff |
| Hash gate | free | volatile-normalised content unchanged |
| Learned noise | free | only lines that changed purely in their numbers (counters, clocks), learned from earlier no-match verdicts |
| Rules | free | `decide` mode (price/stock/new-items/keywords). Edge-triggered: alerts once per episode, again if the price drops ≥3% further |
| Triage | fast model | large diffs that are plausibly unrelated |
| Judge | smart model | everything else. Verdicts are cached by prompt (content-hash fenced) |

The judge must return a **verbatim evidence quote**. It is verified against the page and rejected if it can't be
found. Dedup uses a fingerprint of the event key plus similarity and evidence containment against recent alerts.
LLM outages or budget limits *defer* the run without updating state, so a change is never silently swallowed.

### Act: follow-up before notifying (`app/agents/act.py`)
`analyze → validate → propose`, run under a timeout. It extracts key details, deadlines (each one must be backed by
a quoted line from the page) and links (only links that actually appear on the page). It also writes a comparison
and checklist and drafts a message if asked. It then proposes allowlisted, approval-gated actions:
add-to-calendar (.ics), set reminder, open link, email-me-this-draft, start a follow-up watch (through intake),
and lower the price threshold (owner only). If it fails or times out, the alert still goes out.

### Refinement: self-tuning (`app/agents/refine.py`)
Two "not relevant" marks (or one with a reason) trigger it, debounced. The smart model proposes a sharper condition
plus examples and exclude/require terms. A **backtest** replays the labelled alerts against the old and new specs.
The change is applied automatically only if it keeps every relevant alert, removes at least one irrelevant one,
the owner allows auto-tune, and their plan includes it. Otherwise it becomes a proposal the user can accept.
Every change is a new version with a changelog and the backtest numbers, and versions can be diffed and rolled back.

## Notifications (`app/notify`)
Alert → Act → `fanout_alert` (chunked keyset pagination over subscribers) → per (user, channel) delivery rows →
`send_delivery`.
- Per-user rules: instant vs digest, quiet hours (held until they end, in the user's timezone), an hourly cap
  (overflow goes to the digest), and channel availability (falls back to email).
- Channels: email (Resend with idempotency key, or SMTP), Web Push (VAPID; endpoints restricted to real push
  services), Telegram (deep-link linking; 👍/👎 buttons feed back into self-tuning), and HMAC-signed webhooks (Pro).
- Retries with backoff (5 attempts). Permanent failures disable dead channels: bounced or complained emails go on a
  suppression list, push 404/410 removes the subscription, and a Telegram 403 deactivates the link.
- Digests are built per user at their local digest time, once per day.
- Emails carry a signed one-click `List-Unsubscribe` (RFC 8058) and signed feedback links. A GET only shows a
  confirmation page, because mail scanners prefetch GET links.

## Realtime
Redis Streams: `ev:user:{id}` (alerts, intake progress, deliveries, approvals) and `ev:watch:{id}` (run progress,
shared by all subscribers, so there is no per-subscriber fan-out of run events). `GET /v1/stream` streams SSE.
`Last-Event-ID` encodes the client's position in every subscribed stream, so reconnects replay exactly what was
missed.

## Security model
| Threat | Defence |
|---|---|
| SSRF (users submit URLs) | URL pre-flight (scheme, port, userinfo, reserved TLDs, IP literals incl. octal/hex/IPv4-mapped/NAT64/6to4); DNS resolved **at connect time** in a custom httpcore backend that refuses any non-public address and connects to the exact IP it checked (defeats DNS rebinding and mixed answers); every redirect re-validated; size/time caps; decoded-size cap (zip bombs); content-type allowlist; defusedxml for feeds; Playwright pool intercepts every sub-request. Push endpoints are allowlisted; webhooks must be https and resolve publicly. |
| Prompt injection from pages | hidden DOM and zero-width/bidi characters stripped; instruction-like lines removed and the run marked suspicious (confidence bar raised); content fenced with an HMAC nonce the page can't forge; no tools on page-reading models; schema-validated output; evidence quotes verified; links and dates must be grounded; actions allowlisted and need human approval. |
| Auth | Supabase JWT via JWKS with pinned algorithms (no `none`, no HS256/public-key confusion); `aud`/`iss`/`exp` required; anonymous and service-role tokens rejected; admin role only from `app_metadata`; hashed personal API tokens (Pro), shown once and revocable; login lockout per account and IP; disposable-email blocking (API and Supabase auth hook); open-redirect checks on auth redirects. |
| Abuse / quotas | atomic plan quotas (watches, subscriptions, acts, intake, run-now, LLM tokens/day, sources, interval floor) with advisory locks against races; sliding-window rate limits per route and a global per-IP ceiling; idempotency keys; public watches need a verified email and moderation (rules first, then LLM); auto-hide after 3 reports; global LLM spend breaker (free tier degrades to rule-only, hard cap for all); search budget. |
| Scraping abuse (us hammering sites) | robots.txt honoured (RFC 9309), a per-domain token bucket shared by all workers, shared sources (one fetch serves every watch), conditional GET, block detection with exponential domain backoff, admin denylist. |
| Injection / XSS | parameterised SQL only; strict Pydantic models with length limits; autoescaped templates; Telegram HTML escaping; ReDoS-safe regex validation for user predicates. |
| Privacy (DPDP Act) | data export, account deletion (shared public watches handed to a community account), PII-redacting logs, signed purpose-bound tokens, secrets encrypted at rest (Fernet). |

## Observability
- Structured JSON logs (structlog) with request/run/trace IDs and PII redaction.
- Prometheus metrics: HTTP, runs by outcome/decider, fetch results, LLM calls/tokens/cost/latency, search,
  notifications, scheduler claim lag, queue depth, agent node durations. The API serves `/metrics`; workers serve
  `:9100` and the scheduler `:9101`.
- OpenTelemetry traces (FastAPI, httpx, SQLAlchemy) when `WT_OTEL_EXPORTER_OTLP_ENDPOINT` is set.
  `docker compose --profile observability up` starts Jaeger and Prometheus.
- The same `runs.steps` trace feeds both the user's live view and the admin dashboards
  (`/v1/admin/system`, `/v1/admin/spend`, LLM usage rolled up daily into `llm_usage_daily`).

## Pricing (USD, editable in the `plans` table)
| | Free | Plus $2/mo ($20/yr) | Pro $6/mo ($60/yr) |
|---|---|---|---|
| Own watches | 5 | 30 | 150 |
| Community subscriptions | 25 | 150 | 1000 |
| Fastest check interval | 6 h | 1 h | 15 min |
| Watch → Act follow-ups | 20/mo | 200/mo | 1500/mo |
| History | 30 days | 180 days | 2 years |
| Channels | email, push, Telegram | + per-watch channels | + webhooks, API tokens |
| Self-tuning | proposals | auto-tune | auto-tune |

Community watches are cheap for us: one check and one Act serve every subscriber, and public watches with ≥10
subscribers run on community budget instead of the owner's. Billing is manual for now (admin plan changes are
audited); a payment provider plugs in later by calling the same plan-change path from its webhook.
