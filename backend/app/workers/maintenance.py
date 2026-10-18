"""Periodic maintenance: sweepers (self-healing for lost jobs), retention, stats flush, expiries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text, update

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models import AlertDelivery, IntakeSession
from app.observability.metrics import QUEUE_DEPTH
from app.workers.queue import ALL_QUEUES, Q_AGENTS, Q_NOTIFY, enqueue, queue_depth

log = get_logger(__name__)


async def sweep_stuck(ctx: dict[str, Any] | None = None) -> dict[str, int]:
    """Re-drive work whose job was lost (Redis restart, worker crash). Every job is idempotent."""
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%d%H%M")
    async with session_scope() as s:
        acts = (await s.execute(text(
            "SELECT id FROM alerts WHERE act_status = 'pending' AND created_at < now() - interval '5 minutes' "
            "AND created_at > now() - interval '2 days' LIMIT 200"))).scalars().all()
        fanouts = (await s.execute(text(
            "SELECT id FROM alerts WHERE notify_status = 'pending' AND act_status <> 'pending' "
            "AND created_at < now() - interval '3 minutes' AND created_at > now() - interval '2 days' LIMIT 200"
        ))).scalars().all()
        stuck_sending = (await s.execute(
            update(AlertDelivery).where(AlertDelivery.status == "sending",
                                        AlertDelivery.created_at < now - timedelta(minutes=10))
            .values(status="pending").returning(AlertDelivery.id)
        )).scalars().all()
        pending = (await s.execute(text(
            "SELECT id FROM alert_deliveries WHERE status = 'pending' AND mode = 'instant' "
            "AND created_at < now() - interval '10 minutes' AND created_at > now() - interval '2 days' LIMIT 500"
        ))).scalars().all()
    for aid in acts:
        await enqueue("act_on_alert", str(aid), queue=Q_AGENTS, job_id=f"act:{aid}:sweep:{stamp}")
    for aid in fanouts:
        await enqueue("fanout_alert", str(aid), queue=Q_NOTIFY, job_id=f"fanout:{aid}:sweep:{stamp}")
    for did in {*stuck_sending, *pending}:
        await enqueue("send_delivery", str(did), queue=Q_NOTIFY, job_id=f"dlv:{did}:sweep:{stamp}")
    # expired leases are re-claimed by the scheduler automatically; just report them
    return {"acts": len(acts), "fanouts": len(fanouts), "deliveries": len(set(stuck_sending) | set(pending))}


async def flush_llm_stats(ctx: dict[str, Any] | None = None) -> int:
    r = get_redis()
    n = 0
    for day in (datetime.now(UTC).date(), datetime.now(UTC).date() - timedelta(days=1)):
        data = await r.hgetall(f"llmstat:{day:%Y%m%d}")
        rows: dict[tuple[str, str], dict[str, int]] = {}
        for k, v in data.items():
            try:
                model, purpose, metric = k.rsplit("|", 2)
            except ValueError:
                continue
            rows.setdefault((model, purpose), {})[metric] = int(v)
        if not rows:
            continue
        async with session_scope() as s:
            for (model, purpose), m in rows.items():
                await s.execute(text(
                    """
                    INSERT INTO llm_usage_daily (day, model, purpose, calls, cache_hits, prompt_tokens,
                                                 completion_tokens, cost_usd, errors)
                    VALUES (:day, :model, :purpose, :calls, :hits, :pt, :ct, :cost, :errors)
                    ON CONFLICT (day, model, purpose) DO UPDATE SET
                      calls = EXCLUDED.calls, cache_hits = EXCLUDED.cache_hits, prompt_tokens = EXCLUDED.prompt_tokens,
                      completion_tokens = EXCLUDED.completion_tokens, cost_usd = EXCLUDED.cost_usd,
                      errors = EXCLUDED.errors
                    """
                ), {"day": day, "model": model[:64], "purpose": purpose[:32], "calls": m.get("calls", 0),
                    "hits": m.get("cache_hits", 0), "pt": m.get("prompt_tokens", 0), "ct": m.get("completion_tokens", 0),
                    "cost": m.get("cost_micro", 0) / 1_000_000, "errors": m.get("errors", 0)})
                n += 1
    return n


async def retention(ctx: dict[str, Any] | None = None) -> dict[str, int]:
    """Plan-based history retention + storage hygiene. Runs in bounded batches."""
    out: dict[str, int] = {}
    async with session_scope() as s:
        out["runs"] = (await s.execute(text(
            """
            DELETE FROM runs r USING watches w, profiles p, plans pl
            WHERE r.watch_id = w.id AND w.owner_id = p.id AND pl.id = p.plan_id
              AND r.started_at < now() - make_interval(days => coalesce((pl.limits->>'retention_days')::int, 30))
              AND r.id IN (SELECT id FROM runs WHERE started_at < now() - interval '30 days' LIMIT 20000)
            """
        ))).rowcount or 0
        # raw bodies are only needed for selector re-extraction of recent snapshots
        out["raw_pruned"] = (await s.execute(text(
            """
            UPDATE source_snapshots ss SET raw_z = NULL
            WHERE raw_z IS NOT NULL AND fetched_at < now() - interval '3 days'
              AND NOT EXISTS (SELECT 1 FROM sources so WHERE so.last_snapshot_id = ss.id)
              AND ss.id IN (SELECT id FROM source_snapshots WHERE raw_z IS NOT NULL
                            AND fetched_at < now() - interval '3 days' LIMIT 20000)
            """
        ))).rowcount or 0
        out["snapshots"] = (await s.execute(text(
            """
            DELETE FROM source_snapshots ss
            WHERE ss.fetched_at < now() - interval '30 days'
              AND NOT EXISTS (SELECT 1 FROM sources so WHERE so.last_snapshot_id = ss.id)
              AND NOT EXISTS (SELECT 1 FROM watch_source_state st WHERE st.snapshot_id = ss.id)
              AND ss.id IN (SELECT id FROM source_snapshots WHERE fetched_at < now() - interval '30 days' LIMIT 20000)
            """
        ))).rowcount or 0
        out["deliveries"] = (await s.execute(text(
            "DELETE FROM alert_deliveries WHERE id IN (SELECT id FROM alert_deliveries "
            "WHERE created_at < now() - interval '180 days' LIMIT 20000)"))).rowcount or 0
        out["intake"] = (await s.execute(text(
            "DELETE FROM intake_sessions WHERE updated_at < now() - interval '30 days'"))).rowcount or 0
        out["audit"] = (await s.execute(text(
            "DELETE FROM audit_log WHERE created_at < now() - interval '365 days'"))).rowcount or 0
        out["usage"] = (await s.execute(text(
            "DELETE FROM usage_counters WHERE period_start < now() - interval '120 days'"))).rowcount or 0
        out["orphan_sources"] = (await s.execute(text(
            """
            DELETE FROM sources so WHERE so.created_at < now() - interval '7 days'
              AND NOT EXISTS (SELECT 1 FROM watch_versions v, jsonb_array_elements(v.spec->'sources') src
                              WHERE src->>'url' = so.url)
            """
        ))).rowcount or 0
    log.info("retention_done", **out)
    return out


async def expire_intake(ctx: dict[str, Any] | None = None) -> int:
    async with session_scope() as s:
        res = await s.execute(
            update(IntakeSession).where(IntakeSession.status.in_(("awaiting_user", "proposed")),
                                        IntakeSession.updated_at < datetime.now(UTC) - timedelta(days=7))
            .values(status="expired", view={"message": "This request expired. Start again any time."})
        )
        return res.rowcount or 0


async def queue_metrics(ctx: dict[str, Any] | None = None) -> dict[str, int]:
    out = {}
    for name, q in ALL_QUEUES.items():
        depth = await queue_depth(q)
        QUEUE_DEPTH.labels(queue=name).set(depth)
        out[name] = depth
    return out
