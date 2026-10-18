# Watchtower backend

FastAPI + LangGraph + Supabase (Postgres/Auth) + Groq, with Redis/arq for queues, caching and realtime.
- Design and security model: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- Frontend integration guide: [../docs/API.md](../docs/API.md)

## Run locally
```bash
cp .env.example .env              # fill in keys as you get them; everything works offline with defaults
docker compose up -d postgres redis
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload              # API on :8000 (docs at /docs)
uv run python -m app.workers.scheduler            # scheduler
uv run python -m app.workers.main                 # workers (all queues)
```
To run everything in containers instead: `docker compose --profile app up --build`. Add
`--profile observability` for Jaeger (:16686) and Prometheus (:9090).

With `WT_EMAIL_PROVIDER=console`, emails are logged and kept in the Redis list `outbox:email`, so nothing is
actually sent. For real delivery, set Resend/SMTP keys, VAPID keys (`uv run python scripts/gen_vapid.py`) and a
Telegram bot token (then `uv run python scripts/set_telegram_webhook.py https://your-api`).

### Supabase setup
1. Set `WT_SUPABASE_URL`, the anon key and the service-role key. JWTs are verified against the project's JWKS
   (asymmetric keys). For legacy HS256 projects, set `WT_SUPABASE_JWT_SECRET`.
2. Point `WT_DATABASE_URL` at the project's Postgres (session pooler or direct connection) and run the migrations.
   They enable RLS on every table and add the `profiles → auth.users` FK automatically.
3. Optional: Auth → Hooks → "Before user created" → `POST https://your-api/v1/hooks/auth/before-user-created`
   with the secret in `WT_AUTH_HOOK_SECRET` (blocks disposable emails and sign-up floods).
4. Grant admin with `app_metadata.role = "admin"` on a user (Supabase dashboard / admin API).

## Tests
```bash
uv run pytest                      # everything except live-API tests (~7 min on Windows/Docker Desktop)
uv run pytest -m slow -s           # scale test (sizes via WT_LOAD_WATCHES / WT_LOAD_SOURCES)
uv run pytest -m live -s           # corpus against real Groq/Tavily (needs WT_GROQ_API_KEY, WT_TAVILY_API_KEY)
uv run pytest --cov=app            # coverage
uv run ruff check app tests
```
Tests use real Postgres and Redis (the compose services, separate database `watchtower_test`, Redis db 15), a local
fixture website reached through a fake DNS resolver (so the SSRF guard stays fully on), a scriptable fake LLM,
respx for third-party APIs, and an inline job runner that executes queued arq jobs deterministically.

| Suite | What it covers |
|---|---|
| `tests/unit` | SSRF guard (40+ bypass attempts), extraction/normalisation/diff, block detection, predicates, ReDoS rejection, prompt-injection stripping, quote verification, LLM client (repair, fallback ladder, budgets, cache), search fallback |
| `tests/integration` | shared fetching (single-flight, robots, backoff, 304s), API auth/JWT attacks, community, notifications (quiet hours, caps, digests, Telegram, push, webhooks, bounces), scheduler/workers, SSE replay, admin |
| `tests/agents` | evaluation pipeline end to end, intake routing over a 70+ query corpus (vague, impossible, harmful, contradictory, Hinglish, typos), pre-screen false-positive checks |
| `tests/security` | IDOR, SSRF via API, quota races, rate limits, API tokens, admin boundaries, hostile input |
| `tests/e2e` | plain-English request → clarify → propose → confirm → scheduler → fire → Act → one notification → feedback → self-tuning |
| `tests/load` | hundreds of watches on shared sources through real workers: exactly-once runs, one fetch per source, zero AI calls for unchanged pages |

## Layout
```
app/
  core/          config, db (unit of work + after-commit hooks), redis primitives, auth (JWKS), crypto, errors, logging
  models/        SQLAlchemy models          schemas/  WatchSpec + API models
  fetch/         SSRF-safe client, robots + politeness, extraction, normalisation, diff, block detection, render pool
  llm/           Groq client (ladder, cache, budgets, shared rate governor), prompt-injection defences
  search/        Tavily/Brave + India source registry + ATS/feed patterns
  agents/        intake, evaluate, act, refine graphs; prompts; output schemas; deterministic predicates
  notify/        render (email/push/telegram/webhook), channels, dispatch (fan-out, digests, quiet hours)
  services/      plans & quotas, watches, community, intake sessions, actions, Supabase client
  api/v1/        routers        realtime/  Redis Streams events
  workers/       scheduler, check runner, queue, maintenance crons, worker entrypoint
alembic/         migrations (schema, RLS lockdown, plan/category seed)
```
