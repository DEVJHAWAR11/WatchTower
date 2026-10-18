"""Admin & ops: users/plans (manual billing), suspension, moderation, domain policy, system & spend dashboards."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DB, AdminUser
from app.core.errors import NotFound
from app.llm.client import spend_today_usd
from app.models import (
    AbuseReport,
    AuditLog,
    Check,
    DomainPolicy,
    LlmUsageDaily,
    Plan,
    Profile,
    Run,
    Watch,
)
from app.schemas.api import (
    AdminModerationIn,
    AdminPlanChangeIn,
    AdminSuspendIn,
    DomainPolicyIn,
    PlanLimitsIn,
    ProfileOut,
    WatchOut,
)
from app.services.plans import invalidate_plan_cache
from app.services.watches import set_status
from app.workers.queue import ALL_QUEUES, queue_depth

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[ProfileOut])
async def users(admin: AdminUser, session: DB, q: str | None = Query(None, max_length=100),
                limit: int = Query(50, le=200), offset: int = 0) -> list[Profile]:
    stmt = select(Profile).where(Profile.status != "deleted")
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Profile.email).like(like), func.lower(Profile.handle).like(like)))
    return list((await session.execute(stmt.order_by(Profile.created_at.desc()).limit(limit).offset(offset))).scalars())


@router.post("/users/{user_id}/plan", response_model=ProfileOut)
async def change_plan(user_id: uuid.UUID, body: AdminPlanChangeIn, admin: AdminUser, session: DB) -> Profile:
    """Manual billing provider: plan changes are explicit, audited admin actions until a gateway is wired in."""
    p = await session.get(Profile, user_id)
    if p is None:
        raise NotFound("User not found")
    old = p.plan_id
    p.plan_id = body.plan_id
    p.plan_expires_at = body.expires_at
    session.add(AuditLog(actor_id=admin.id, action="admin.plan_change", target_type="user", target_id=str(user_id),
                         meta={"from": old, "to": body.plan_id, "reason": body.reason,
                               "expires_at": body.expires_at.isoformat() if body.expires_at else None}))
    return p


@router.post("/users/{user_id}/suspend", response_model=ProfileOut)
async def suspend(user_id: uuid.UUID, body: AdminSuspendIn, admin: AdminUser, session: DB) -> Profile:
    p = await session.get(Profile, user_id)
    if p is None:
        raise NotFound("User not found")
    p.status = "suspended" if body.suspend else "active"
    p.status_reason = body.reason if body.suspend else None
    await session.execute(update(Check).where(Check.watch_id.in_(select(Watch.id).where(Watch.owner_id == user_id)))
                          .values(enabled=not body.suspend))
    if body.suspend:
        await session.execute(update(Watch).where(Watch.owner_id == user_id, Watch.visibility == "public")
                              .values(moderation_status="pending", moderation_reason="Owner suspended"))
    session.add(AuditLog(actor_id=admin.id, action="admin.suspend" if body.suspend else "admin.unsuspend",
                         target_type="user", target_id=str(user_id), meta={"reason": body.reason}))
    return p


@router.get("/moderation", response_model=list[WatchOut])
async def moderation_queue(admin: AdminUser, session: DB) -> list[Watch]:
    return list((await session.execute(select(Watch).where(Watch.visibility == "public", Watch.moderation_status == "pending")
                                       .order_by(Watch.report_count.desc(), Watch.updated_at).limit(100))).scalars())


@router.post("/watches/{watch_id}/moderation", response_model=WatchOut)
async def moderate(watch_id: uuid.UUID, body: AdminModerationIn, admin: AdminUser, session: DB) -> Watch:
    w = await session.get(Watch, watch_id)
    if w is None:
        raise NotFound("Watch not found")
    w.moderation_status = "approved" if body.decision == "approve" else "rejected"
    w.moderation_reason = body.reason
    if body.decision == "reject":
        w.visibility = "private"
    await session.execute(update(AbuseReport).where(AbuseReport.watch_id == watch_id, AbuseReport.status == "open")
                          .values(status="actioned" if body.decision == "reject" else "dismissed"))
    session.add(AuditLog(actor_id=admin.id, action=f"admin.moderation.{body.decision}", target_type="watch",
                         target_id=str(watch_id), meta={"reason": body.reason}))
    return w


@router.post("/watches/{watch_id}/disable", response_model=WatchOut)
async def disable_watch(watch_id: uuid.UUID, admin: AdminUser, session: DB, reason: str = Query(..., max_length=300)) -> Watch:
    w = await session.get(Watch, watch_id)
    if w is None:
        raise NotFound("Watch not found")
    await set_status(session, w, "paused", f"Disabled by moderators: {reason}")
    session.add(AuditLog(actor_id=admin.id, action="admin.watch_disable", target_type="watch", target_id=str(watch_id),
                         meta={"reason": reason}))
    return w


@router.get("/reports")
async def reports(admin: AdminUser, session: DB, status: str = "open") -> list[dict[str, Any]]:
    rows = (await session.execute(select(AbuseReport).where(AbuseReport.status == status)
                                  .order_by(AbuseReport.created_at.desc()).limit(200))).scalars()
    return [{"id": str(r.id), "watch_id": str(r.watch_id), "reason": r.reason, "detail": r.detail,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/domains")
async def domains(admin: AdminUser, session: DB, blocked_only: bool = False) -> list[dict[str, Any]]:
    stmt = select(DomainPolicy)
    if blocked_only:
        stmt = stmt.where(or_(DomainPolicy.blocked_until > func.now(), DomainPolicy.denylisted.is_(True)))
    rows = (await session.execute(stmt.order_by(DomainPolicy.updated_at.desc()).limit(500))).scalars()
    return [{"domain": d.domain, "denylisted": d.denylisted, "blocked_until": d.blocked_until, "block_reason": d.block_reason,
             "block_count": d.block_count, "needs_render": d.needs_render, "min_interval_seconds": d.min_interval_seconds,
             "notes": d.notes} for d in rows]


@router.put("/domains/{domain}")
async def set_domain(domain: str, body: DomainPolicyIn, admin: AdminUser, session: DB) -> dict[str, Any]:
    domain = domain.lower().strip()[:255]
    await session.execute(pg_insert(DomainPolicy).values(domain=domain).on_conflict_do_nothing())
    d = await session.get(DomainPolicy, domain)
    data = body.model_dump(exclude_unset=True)
    if data.pop("clear_block", False):
        d.blocked_until, d.block_count, d.block_reason = None, 0, None
    for k, v in data.items():
        setattr(d, k, v)
    session.add(AuditLog(actor_id=admin.id, action="admin.domain_policy", target_type="domain", target_id=domain,
                         meta=body.model_dump(mode="json", exclude_unset=True)))
    return {"domain": domain, "denylisted": d.denylisted, "needs_render": d.needs_render}


@router.put("/plans/{plan_id}")
async def update_plan(plan_id: str, body: PlanLimitsIn, admin: AdminUser, session: DB) -> dict[str, Any]:
    p = await session.get(Plan, plan_id)
    if p is None:
        raise NotFound("Plan not found")
    if body.limits:
        p.limits = {**p.limits, **body.limits}
    if body.features:
        p.features = {**p.features, **body.features}
    session.add(AuditLog(actor_id=admin.id, action="admin.plan_update", target_type="plan", target_id=plan_id,
                         meta=body.model_dump(exclude_none=True)))
    invalidate_plan_cache()
    return {"id": p.id, "limits": p.limits, "features": p.features}


@router.get("/system")
async def system(admin: AdminUser, session: DB) -> dict[str, Any]:
    now = datetime.now(UTC)
    hour = now - timedelta(hours=1)
    outcomes = dict((await session.execute(select(Run.outcome, func.count()).where(Run.started_at >= hour)
                                           .group_by(Run.outcome))).all())
    decided = dict((await session.execute(select(Run.decided_by, func.count()).where(Run.started_at >= hour)
                                          .group_by(Run.decided_by))).all())
    overdue = await session.scalar(select(func.count()).select_from(Check).where(
        Check.enabled.is_(True), Check.next_run_at < now - timedelta(minutes=2), Check.lease_until.is_(None)))
    oldest = await session.scalar(select(func.min(Check.next_run_at)).where(Check.enabled.is_(True),
                                                                            Check.lease_until.is_(None)))
    counts = (await session.execute(text(
        "SELECT (SELECT count(*) FROM profiles WHERE status='active'), (SELECT count(*) FROM watches WHERE status='active'),"
        " (SELECT count(*) FROM watches WHERE visibility='public' AND moderation_status='approved'),"
        " (SELECT count(*) FROM alerts WHERE created_at > now() - interval '24 hours'),"
        " (SELECT count(*) FROM alert_deliveries WHERE status='failed' AND created_at > now() - interval '24 hours')"
    ))).one()
    queues = {name: await queue_depth(q) for name, q in ALL_QUEUES.items()}
    total = sum(outcomes.values()) or 0
    return {
        "time": now.isoformat(),
        "queues": queues,
        "scheduler": {"overdue_checks": overdue or 0,
                      "max_lag_seconds": max(0, int((now - oldest).total_seconds())) if oldest and oldest < now else 0},
        "runs_last_hour": {"total": total, "by_outcome": outcomes, "by_decider": decided,
                           "llm_skip_ratio": round(1 - decided.get("llm", 0) / total, 3) if total else None},
        "totals": {"active_users": counts[0], "active_watches": counts[1], "public_watches": counts[2],
                   "alerts_24h": counts[3], "failed_deliveries_24h": counts[4]},
        "llm_spend_today_usd": round(await spend_today_usd(), 4),
    }


@router.get("/spend")
async def spend(admin: AdminUser, session: DB, days: int = Query(14, ge=1, le=90)) -> dict[str, Any]:
    since = date.today() - timedelta(days=days)
    rows = (await session.execute(select(LlmUsageDaily).where(LlmUsageDaily.day >= since)
                                  .order_by(LlmUsageDaily.day.desc()))).scalars().all()
    by_day: dict[str, float] = {}
    for r in rows:
        by_day[r.day.isoformat()] = by_day.get(r.day.isoformat(), 0.0) + float(r.cost_usd)
    return {"by_day_usd": by_day, "rows": [
        {"day": r.day.isoformat(), "model": r.model, "purpose": r.purpose, "calls": r.calls, "cache_hits": r.cache_hits,
         "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens, "cost_usd": float(r.cost_usd),
         "errors": r.errors} for r in rows]}


@router.get("/audit")
async def audit(admin: AdminUser, session: DB, action: str | None = None, limit: int = Query(100, le=500)) -> list[dict[str, Any]]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = (await session.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit))).scalars()
    return [{"id": str(a.id), "actor_id": str(a.actor_id) if a.actor_id else None, "action": a.action,
             "target_type": a.target_type, "target_id": a.target_id, "meta": a.meta, "created_at": a.created_at.isoformat()}
            for a in rows]
