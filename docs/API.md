# Watchtower API: frontend integration guide

Base URL: `/v1`. The full OpenAPI schema is at `/openapi.json` and the interactive docs at `/docs` (in non-prod
environments).

## Conventions
- **Auth**: `Authorization: Bearer <Supabase access token>`. Pro users can also use personal tokens (`wt_…`).
- **Errors** always look like this:
  `{"error": {"code": "quota_exceeded", "message": "…human readable…", "details": {...}, "request_id": "…"}}`.
  Common codes: `unauthorized` (401), `token_expired` (401 → refresh), `forbidden` (403), `not_found` (404),
  `conflict` (409), `validation_failed` (422), `quota_exceeded` (402, with `details.metric` and `details.limit`,
  so you can show an upgrade prompt), `rate_limited` (429 + `Retry-After`).
- **Idempotency**: send `Idempotency-Key: <uuid>` on `POST /intake` and `POST /watches` so double-clicks and
  retries don't create duplicates.
- **Pagination**: list endpoints return `{items, next_cursor}`. Pass `?cursor=` to get the next page.
- Every response carries `X-Request-ID`. Show it in error reports.

## Auth (proxied Supabase Auth)
| Action | Endpoint |
|---|---|
| Sign up | `POST /auth/signup {email, password, display_name?, redirect_to?}` → session or "check your inbox" |
| Sign in | `POST /auth/login {email, password}` → `{access_token, refresh_token, expires_in, user}` |
| Refresh | `POST /auth/refresh {refresh_token}` |
| Magic link / OTP | `POST /auth/magic-link {email}`, `POST /auth/verify-otp {email, token}` |
| Forgot / change password | `POST /auth/password/recover {email}`, `POST /auth/password {password}` |
| OAuth | `GET /auth/oauth/google?redirect_to=…` → `message` holds the URL to redirect to |
| Sign out | `POST /auth/logout?scope=local\|global` |

You can also use `supabase-js` directly against Supabase. The API accepts its tokens all the same.
`redirect_to` must be a URL on the frontend origin.

## Creating a watch (conversational)
```
POST /intake {query}                       → 202 {id, status:"queued"}
  stream `intake.updated` events (or poll GET /intake/{id}) until status is one of:
  awaiting_user  view.questions[{id, question, options[]}]   → POST /intake/{id}/answer {answers:{id: text}}
                 view.stage == "need_url": ask for a link    → POST /intake/{id}/answer {answers:{url: "https://…"}}
  proposed       view.proposal {title, condition, sources[], interval_minutes, min_interval_minutes, rules[],
                 uses_ai_judgement, fire_once, follow_up_tasks}, view.dry_run {already_met, reason, evidence},
                 view.similar_public_watches[] (offer "subscribe instead")
                 → POST /intake/{id}/confirm {confirm:true, edits:{title?, condition?, interval_minutes?,
                   visibility?, delivery_mode?, fire_once?}}   or {confirm:false}
  created        view.watch_id
  refused | rejected | failed   view.message (+ view.alternatives[] for rejections)
```
Statuses while working: `queued`, `running` (with `stage`: understanding / searching / checking_pages / testing).

Power users can skip the agent: `POST /watches {title, spec, visibility?, category?}`.

## A watch's live view
`GET /watches/{id}/state` returns everything in one call:
- `watch`: title, status (`active|paused|error|completed|expired|archived`), status_reason, visibility,
  subscriber_count, is_owner, is_subscribed, owner {handle, is_community}
- `schedule`: `{enabled, interval_seconds, next_run_at, last_run_at, running, consecutive_failures}`
- `last_run`: `{outcome, decided_by, llm_called, reason, diff_summary, steps[{node, status, note, ms}], …}`
  - outcome: `baseline | skipped_unchanged | no_match | matched | duplicate | deferred | blocked | error`
  - decided_by: `hash | noise | rule | triage | llm | cache | none`. Use it for "AI skipped / AI checked" badges.
- `last_alert`, `stats` (7-day runs, AI calls, AI skip ratio, alerts, errors), `sources[]` (status/last fetch)
- owner only: `current_version` (the spec), `pending_refinement`

Then open `GET /stream?watch={id}` for live updates (see below).

Other watch endpoints: `GET /watches/{id}/runs` (cursor; `?outcome=`), `GET /watches/{id}/runs/{run_id}`
(full step trace), `GET /watches/{id}/alerts`, `POST /watches/{id}/run` (check now, counts against a daily quota),
`POST /watches/{id}/pause|resume`, `PATCH /watches/{id}`, `DELETE /watches/{id}` (archive),
`POST /watches/{id}/fork`.

Versions and self-tuning: `GET /watches/{id}/versions`, `GET /watches/{id}/versions/diff?a=1&b=2`,
`POST /watches/{id}/versions/{n}/rollback`, `PUT /watches/{id}/spec`, `GET /watches/{id}/refinements`,
`POST /watches/{id}/refinements/{pid}/accept|reject`, `POST /watches/{id}/refine`.

## Alerts, feedback, actions
- `GET /alerts` (inbox across all watches, cursor) and `GET /alerts/{id}`. Each alert has `title`, `summary`,
  `key_facts`, `evidence`, `source_url`, `act_status`,
  `act_result {headline, what_happened, key_details, deadlines[{label, date}], links[{name, url}], comparison,
  checklist[], draft_message}`, `actions[{id, kind, title, payload, owner_only, expires_at, decision, result}]`,
  and `my_feedback`.
- `POST /alerts/{id}/feedback {relevant, reason?}`. This drives self-tuning, so show 👍/👎 on every alert.
- `POST /actions/{id}/approve|reject`. The result depends on the action kind:
  - `add_to_calendar` → `{ics_url}`
  - `set_reminder` → `{remind_at}`
  - `open_link` → `{url}`
  - `draft_email` → sends the draft to the user
  - `create_followup_watch` → `{intake_session_id}` (continue it like any intake)
  - `adjust_threshold` → `{version}`

## Community
`GET /explore?sort=trending|popular|new|recently_fired&category=&q=`, `GET /explore/categories`,
`GET /explore/collections` (India-first rows: exams, placements, scholarships & IPOs, deals),
`GET /explore/watches/{slug}`, `POST /watches/{id}/subscribe {delivery_mode?, channels?}`,
`DELETE /watches/{id}/subscribe`, `PATCH /watches/{id}/subscription {delivery_mode?, channels?, muted?}`,
`POST /watches/{id}/report {reason, detail?}`. To publish, call `PATCH /watches/{id} {visibility:"public"}`. It
then goes through moderation: `moderation_status` changes from `pending` to `approved` or `rejected`.

## Account & settings
`GET /me`, `PATCH /me/settings` (timezone, quiet hours, digest time, default channels, delivery mode, max alerts per
hour, auto-tune, handle), `GET /me/usage` (plan limits and current usage, for meters), `GET /plans`,
`GET /me/watches?role=owner|subscriber`, `GET /me/deliveries`, `GET /me/export`, `DELETE /me?confirm=DELETE`,
`GET|POST|DELETE /me/api-tokens` (Pro).

## Notification channels
`GET /notifications/channels` (status of email, push, Telegram and webhooks, plus the VAPID public key) ·
`POST /notifications/push {endpoint, keys:{p256dh, auth}}` (pass the browser `PushSubscription.toJSON()`) ·
`DELETE /notifications/push?endpoint=` · `POST /notifications/telegram/link` → `{deep_link}` (open it; the user
taps Start) · `DELETE /notifications/telegram` · `POST /notifications/webhooks {url}` (Pro; returns the signing
secret once) · `POST /notifications/test`.

Push payloads look like `{title, body, url, tag, data:{alert_id, watch_id}}`. Open `url` when the notification is
clicked.

## Realtime (SSE)
`GET /stream?watch=<id>&watch=<id2>` (up to 10 watches, plus the user's own stream automatically).
- Auth: an `Authorization` header (with a fetch-based client such as `@microsoft/fetch-event-source`), or
  `POST /stream/ticket` followed by `GET /stream?ticket=…` for native `EventSource` (tickets last 60s).
- Reconnects: send the last `id` you received as `Last-Event-ID` (or `?since=`) and missed events are replayed.
- Every `data` payload is `{scope: "user"|"watch", stream, type, at, data}`.

| Event | Scope | When |
|---|---|---|
| `ready` | — | connection established |
| `intake.updated` | user | intake progress / questions / proposal / created (`data.view` = same as GET /intake) |
| `run.started` | watch | a check began |
| `run.step` | watch | each agent step: `{node, status, note, ms}` (fetch, change_gate, rules, triage, judge, dedup, fire) |
| `run.completed` | watch | `{outcome, decided_by, reason, llm_called, alert_id}` |
| `watch.scheduled` | watch | `{next_run_at, status}` |
| `act.started` / `act.completed` | watch | follow-up work on an alert |
| `watch.refined` | watch | self-tuning applied a new version |
| `feedback.recorded` | watch | someone gave feedback |
| `alert.created` | user | an alert for you (`held: true` during quiet hours, `mode: digest` when batched) |
| `delivery.sent` | user | a notification went out on a channel |
| `notification` | user | system notices (watch paused, moderation, reminders, refinement) |
| `refinement.proposed` | user | a suggested improvement awaits your approval |

Comment lines (`: ping`) arrive every 15s as keep-alives.
