"""Account, settings, usage, plans, API tokens, data export & deletion (DPDP Act)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, delete, func, select, update

from app.api.deps import DB, CurrentUser, rate_limit
from app.core.crypto import new_api_token
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.logging import get_logger
from app.llm.client import user_tokens_today
from app.models import (
    Alert,
    AlertDelivery,
    ApiToken,
    AuditLog,
    Check,
    Feedback,
    IntakeSession,
    Plan,
    Profile,
    PushSubscription,
    Run,
    Subscription,
    TelegramLink,
    Watch,
    WatchVersion,
    WebhookEndpoint,
)
from app.schemas.api import (
    ApiTokenIn,
    ApiTokenOut,
    DeliveryOut,
    PlanOut,
    PlanRequestIn,
    ProfileOut,
    SettingsIn,
    UsageOut,
    WatchOut,
)
from app.services.community import transfer_public_watches
from app.services.plans import count_owned_watches, count_subscriptions, plan_for, usage_value
from app.services.supabase import get_supabase_auth

router = APIRouter(tags=["account"])
log = get_logger(__name__)


@router.get("/me", response_model=ProfileOut)
async def me(user: CurrentUser) -> Profile:
    return user


@router.patch("/me/settings", response_model=ProfileOut)
async def update_settings(body: SettingsIn, user: CurrentUser, session: DB) -> Profile:
    data = body.model_dump(exclude_unset=True)
    if data.pop("clear_quiet_hours", False):
        user.quiet_hours_start = None
        user.quiet_hours_end = None
    if "handle" in data and data["handle"] and data["handle"] != user.handle:
        taken = await session.scalar(select(Profile.id).where(func.lower(Profile.handle) == data["handle"],
                                                              Profile.id != user.id))
        if taken:
            raise Conflict("That handle is taken")
    if "default_channels" in data:
        plan = await plan_for(session, user)
        allowed = set(plan.feature("channels") or [])
        bad = [c for c in data["default_channels"] if c not in allowed]
        if bad:
            raise Forbidden(f"Your plan doesn't include: {', '.join(bad)}")
    if "max_alerts_per_hour" in data:
        plan = await plan_for(session, user)
        data["max_alerts_per_hour"] = min(data["max_alerts_per_hour"], plan.limit("max_alerts_per_hour"))
    if ("quiet_hours_start" in data) != ("quiet_hours_end" in data):
        raise Conflict("Set both quiet_hours_start and quiet_hours_end")
    for k, v in data.items():
        setattr(user, k, v)
    if "auto_tune" in data:
        await session.execute(update(Watch).where(Watch.owner_id == user.id).values(auto_tune=data["auto_tune"]))
    await session.flush()
    return user


@router.get("/plans", response_model=list[PlanOut])
async def plans(session: DB) -> list[PlanOut]:
    rows = (await session.execute(select(Plan).where(Plan.is_public.is_(True)).order_by(Plan.sort))).scalars()
    return [PlanOut(id=p.id, name=p.name, price_usd_month=float(p.price_usd_month), price_usd_year=float(p.price_usd_year),
                    limits=p.limits, features=p.features) for p in rows]


@router.get("/me/usage", response_model=UsageOut)
async def usage(user: CurrentUser, session: DB) -> UsageOut:
    plan = await plan_for(session, user)
    p = await session.get(Plan, plan.id)
    return UsageOut(
        plan=PlanOut(id=p.id, name=p.name, price_usd_month=float(p.price_usd_month),
                     price_usd_year=float(p.price_usd_year), limits=plan.limits, features=plan.features),
        watches=await count_owned_watches(session, user.id),
        subscriptions=await count_subscriptions(session, user.id),
        acts_this_month=await usage_value(session, user.id, "acts", "month"),
        intake_today=await usage_value(session, user.id, "intake", "day"),
        run_now_today=await usage_value(session, user.id, "run_now", "day"),
        llm_tokens_today=await user_tokens_today(user.id),
    )


@router.get("/me/watches", response_model=list[WatchOut])
async def my_watches(user: CurrentUser, session: DB,
                     role: str = Query("all", pattern="^(all|owner|subscriber)$"),
                     include_archived: bool = False) -> list[WatchOut]:
    q = select(Watch, Subscription).join(Subscription, Subscription.watch_id == Watch.id).where(
        Subscription.user_id == user.id)
    if role != "all":
        q = q.where(Subscription.role == role)
    if not include_archived:
        q = q.where(Watch.status != "archived")
    rows = (await session.execute(q.order_by(Watch.updated_at.desc()).limit(500))).all()
    out = []
    for w, sub in rows:
        wo = WatchOut.model_validate(w)
        wo.is_owner = w.owner_id == user.id
        wo.is_subscribed = sub.role == "subscriber"
        out.append(wo)
    return out


DASH_BUCKETS = 14
DASH_BUCKET_SECONDS = 12 * 3600


@router.get("/me/dashboard")
async def dashboard(user: CurrentUser, session: DB) -> dict[str, Any]:
    """One call for the dashboard: totals plus, per watch, its schedule, last outcome and a 7-day activity strip."""
    rows = (await session.execute(
        select(Watch, Subscription.role, Check).join(Subscription, Subscription.watch_id == Watch.id)
        .outerjoin(Check, Check.watch_id == Watch.id)
        .where(Subscription.user_id == user.id, Watch.status != "archived")
        .order_by(Watch.updated_at.desc()).limit(500)
    )).all()
    ids = [w.id for w, _, _ in rows]
    now = datetime.now(UTC)
    since = now - timedelta(seconds=DASH_BUCKETS * DASH_BUCKET_SECONDS)
    activity: dict[uuid.UUID, list[dict[str, int]]] = {
        i: [{"runs": 0, "alerts": 0, "errors": 0} for _ in range(DASH_BUCKETS)] for i in ids}
    last_runs: dict[uuid.UUID, Run] = {}
    totals = {"checks_today": 0, "alerts_7d": 0, "runs_7d": 0, "ai_skipped_7d": 0}
    alerts_24h: dict[uuid.UUID, int] = {}
    if ids:
        bucket = func.floor(func.extract("epoch", now - Run.started_at) / DASH_BUCKET_SECONDS)
        agg = (await session.execute(
            select(Run.watch_id, bucket, func.count(), func.count().filter(Run.outcome == "matched"),
                   func.count().filter(Run.outcome.in_(("error", "blocked"))),
                   func.count().filter(Run.llm_called.is_(False)))
            .where(Run.watch_id.in_(ids), Run.started_at >= since).group_by(Run.watch_id, bucket)
        )).all()
        for wid, b, n, matched, errs, skipped in agg:
            idx = DASH_BUCKETS - 1 - int(b)
            if 0 <= idx < DASH_BUCKETS:
                activity[wid][idx] = {"runs": n, "alerts": matched, "errors": errs}
            totals["runs_7d"] += n
            totals["alerts_7d"] += matched
            totals["ai_skipped_7d"] += skipped
            if int(b) < 2:
                alerts_24h[wid] = alerts_24h.get(wid, 0) + matched
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(user.timezone or "Asia/Kolkata")
        except Exception:  # noqa: BLE001 - unknown zone: fall back to UTC midnight
            tz = UTC
        midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        totals["checks_today"] = int(await session.scalar(select(func.count()).select_from(Run).where(
            Run.watch_id.in_(ids), Run.started_at >= midnight)) or 0)
        latest = (select(Run.watch_id, func.max(Run.started_at).label("ts")).where(Run.watch_id.in_(ids))
                  .group_by(Run.watch_id).subquery())
        for r in (await session.execute(select(Run).join(latest, and_(
                Run.watch_id == latest.c.watch_id, Run.started_at == latest.c.ts)))).scalars():
            last_runs[r.watch_id] = r
    items = []
    for w, role, chk in rows:
        wo = WatchOut.model_validate(w)
        wo.is_owner = w.owner_id == user.id
        wo.is_subscribed = role == "subscriber"
        lr = last_runs.get(w.id)
        items.append({
            "watch": wo.model_dump(mode="json"),
            "schedule": {
                "enabled": bool(chk and chk.enabled), "interval_seconds": chk.interval_seconds if chk else None,
                "next_run_at": chk.next_run_at.isoformat() if chk and chk.enabled and chk.next_run_at else None,
                "last_run_at": chk.last_run_at.isoformat() if chk and chk.last_run_at else None,
                "running": bool(chk and chk.lease_until and chk.lease_until > now),
                "consecutive_failures": chk.consecutive_failures if chk else 0,
            },
            "last_run": {"outcome": lr.outcome, "decided_by": lr.decided_by, "llm_called": lr.llm_called,
                         "reason": lr.reason, "started_at": lr.started_at.isoformat(),
                         "status": lr.status} if lr else None,
            "alerts_24h": alerts_24h.get(w.id, 0),
            "activity": activity.get(w.id, []),
        })
    active = sum(1 for w, _, _ in rows if w.status == "active")
    return {"totals": {"watches": len(rows), "active_watches": active, **totals},
            "bucket_hours": DASH_BUCKET_SECONDS // 3600, "items": items}


@router.get("/me/deliveries", response_model=list[DeliveryOut])
async def my_deliveries(user: CurrentUser, session: DB, limit: int = Query(50, ge=1, le=200)) -> list[AlertDelivery]:
    return list((await session.execute(
        select(AlertDelivery).where(AlertDelivery.user_id == user.id).order_by(AlertDelivery.created_at.desc()).limit(limit)
    )).scalars())


@router.post("/me/plan-request", status_code=202, dependencies=[Depends(rate_limit("plan_request", 5, 86400))])
async def plan_request(body: PlanRequestIn, user: CurrentUser, session: DB) -> dict[str, str]:
    """Until a payment provider is wired in, upgrades are applied by an admin. This records the request for them."""
    if body.plan_id == user.plan_id:
        raise Conflict("You're already on that plan")
    exists = await session.scalar(select(Plan.id).where(Plan.id == body.plan_id, Plan.is_public.is_(True)))
    if not exists:
        raise NotFound("Unknown plan")
    session.add(AuditLog(actor_id=user.id, action="plan.request", target_type="user", target_id=str(user.id),
                         meta={"plan_id": body.plan_id, "from": user.plan_id, "note": body.note}))
    return {"status": "received", "message": "Thanks! We'll switch your plan and email you shortly."}


# ------------------------------------------------------------------ API tokens (Pro)
@router.get("/me/api-tokens", response_model=list[ApiTokenOut])
async def list_tokens(user: CurrentUser, session: DB) -> list[ApiToken]:
    return list((await session.execute(select(ApiToken).where(ApiToken.user_id == user.id)
                                       .order_by(ApiToken.created_at.desc()))).scalars())


@router.post("/me/api-tokens", dependencies=[Depends(rate_limit("apitoken", 10, 3600))])
async def create_token(body: ApiTokenIn, user: CurrentUser, session: DB) -> dict[str, Any]:
    plan = await plan_for(session, user)
    if not plan.feature("api_tokens"):
        raise Forbidden("API tokens are available on the Pro plan")
    n = await session.scalar(select(func.count()).select_from(ApiToken).where(
        ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None)))
    if (n or 0) >= 10:
        raise Conflict("You can have at most 10 active tokens")
    token, prefix, digest = new_api_token()
    exp = datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    row = ApiToken(user_id=user.id, name=body.name, prefix=prefix, token_hash=digest, scopes=["all"], expires_at=exp)
    session.add(row)
    session.add(AuditLog(actor_id=user.id, action="api_token.create", target_type="api_token", target_id=prefix))
    await session.flush()
    return {"token": token, "token_info": ApiTokenOut.model_validate(row).model_dump(mode="json"),
            "note": "Store this token now. It won't be shown again."}


@router.delete("/me/api-tokens/{token_id}", status_code=204)
async def revoke_token(token_id: uuid.UUID, user: CurrentUser, session: DB) -> None:
    row = await session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise NotFound("Token not found")
    row.revoked_at = datetime.now(UTC)
    session.add(AuditLog(actor_id=user.id, action="api_token.revoke", target_type="api_token", target_id=row.prefix))


# ------------------------------------------------------------------ export / delete
@router.get("/me/export", dependencies=[Depends(rate_limit("export", 3, 3600))])
async def export_data(user: CurrentUser, session: DB) -> dict[str, Any]:
    """Machine-readable export of everything we hold about the user (right to access)."""
    owned = (await session.execute(select(Watch).where(Watch.owner_id == user.id))).scalars().all()
    versions = (await session.execute(select(WatchVersion).where(
        WatchVersion.watch_id.in_([w.id for w in owned])))).scalars().all() if owned else []
    subs = (await session.execute(select(Subscription).where(Subscription.user_id == user.id))).scalars().all()
    alerts = (await session.execute(select(Alert).where(Alert.watch_id.in_([s.watch_id for s in subs]))
                                    .order_by(Alert.created_at.desc()).limit(5000))).scalars().all() if subs else []
    fb = (await session.execute(select(Feedback).where(Feedback.user_id == user.id))).scalars().all()
    intake = (await session.execute(select(IntakeSession).where(IntakeSession.user_id == user.id))).scalars().all()
    deliveries = (await session.execute(select(AlertDelivery).where(AlertDelivery.user_id == user.id)
                                        .order_by(AlertDelivery.created_at.desc()).limit(5000))).scalars().all()

    def row(o: Any, cols: list[str]) -> dict[str, Any]:
        return {c: getattr(o, c) for c in cols}

    session.add(AuditLog(actor_id=user.id, action="account.export"))
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "profile": ProfileOut.model_validate(user).model_dump(mode="json"),
        "watches": [row(w, ["id", "title", "description", "query_text", "visibility", "status", "created_at"]) for w in owned],
        "watch_versions": [row(v, ["watch_id", "version", "spec", "changelog", "created_at"]) for v in versions],
        "subscriptions": [row(s, ["watch_id", "role", "delivery_mode", "channels", "muted", "created_at"]) for s in subs],
        "alerts": [row(a, ["id", "watch_id", "title", "summary", "key_facts", "source_url", "created_at"]) for a in alerts],
        "feedback": [row(f, ["alert_id", "relevant", "reason", "created_at"]) for f in fb],
        "intake_sessions": [row(i, ["id", "query", "status", "created_at"]) for i in intake],
        "deliveries": [row(d, ["alert_id", "channel", "kind", "status", "created_at", "sent_at"]) for d in deliveries],
    }


@router.delete("/me", status_code=202, dependencies=[Depends(rate_limit("delete_account", 3, 3600))])
async def delete_account(user: CurrentUser, session: DB, confirm: str = Query(...)) -> dict[str, str]:
    """Right to erasure. Public watches other people rely on are handed to the community account."""
    if confirm != "DELETE":
        raise Conflict("Pass confirm=DELETE to permanently delete your account")
    uid = user.id
    transferred = await transfer_public_watches(session, uid)
    await session.execute(delete(Watch).where(Watch.owner_id == uid))
    for model in (Subscription, PushSubscription, TelegramLink, WebhookEndpoint, ApiToken, IntakeSession, Feedback,
                  AlertDelivery):
        await session.execute(delete(model).where(model.user_id == uid))
    user.status = "deleted"
    user.deleted_at = datetime.now(UTC)
    user.email = None
    user.display_name = None
    user.handle = None
    session.add(AuditLog(actor_id=None, action="account.delete", target_type="user", target_id=str(uid),
                         meta={"transferred_public_watches": transferred}))
    await session.flush()
    try:
        await get_supabase_auth().admin_delete_user(uid)
    except Exception as e:  # identity deletion can be retried by an admin; local data is already gone
        log.error("supabase_delete_failed", user_id=str(uid), error=str(e))
    await session.execute(delete(Profile).where(Profile.id == uid))
    return {"status": "deleted"}
