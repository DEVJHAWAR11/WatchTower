"""Watches: CRUD, lifecycle, live state, runs, alerts, versions, refinements, community actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy import and_, func, select

from app.api.deps import DB, CurrentUser, Idempotency, OptionalUser, idempotency, rate_limit
from app.api.v1.common import alert_out, decode_cursor, encode_cursor, owner_out
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models import (
    Alert,
    AuditLog,
    Check,
    Profile,
    RefinementProposal,
    Run,
    Source,
    Subscription,
    Watch,
    WatchVersion,
)
from app.schemas.api import (
    AlertOut,
    Page,
    RefinementOut,
    ReportIn,
    RunDetailOut,
    RunOut,
    SpecUpdateIn,
    SubscriptionPrefsIn,
    VersionOut,
    WatchCreateIn,
    WatchOut,
    WatchStateOut,
    WatchUpdateIn,
)
from app.schemas.spec import WatchSpec
from app.services import community
from app.services.plans import consume, plan_for
from app.services.watches import (
    create_watch,
    fork_watch,
    get_watch_for_user,
    new_version,
    run_now,
    set_status,
)

router = APIRouter(prefix="/watches", tags=["watches"])


async def watch_out(session: Any, w: Watch, user: Profile | None) -> WatchOut:
    wo = WatchOut.model_validate(w)
    wo.is_owner = user is not None and w.owner_id == user.id
    if user is not None and not wo.is_owner:
        wo.is_subscribed = bool(await session.scalar(select(Subscription.id).where(
            Subscription.watch_id == w.id, Subscription.user_id == user.id)))
    wo.owner = await owner_out(session, w.owner_id)
    return wo


def _validate_spec(raw: dict[str, Any]) -> WatchSpec:
    try:
        return WatchSpec.model_validate(raw)
    except ValidationError as e:
        raise ValidationFailed("Invalid watch definition", details=e.errors(include_url=False, include_context=False)) from e


@router.post("", response_model=WatchOut, status_code=201, dependencies=[Depends(rate_limit("watch_create", 30, 3600))])
async def create(body: WatchCreateIn, user: CurrentUser, session: DB,
                 idem: Idempotency = Depends(idempotency)) -> WatchOut:
    if (cached := await idem.cached()) is not None:
        w = await get_watch_for_user(session, uuid.UUID(cached["id"]), user)
        return await watch_out(session, w, user)
    spec = _validate_spec(body.spec)
    plan = await plan_for(session, user)
    w = await create_watch(session, owner=user, plan=plan, spec=spec, title=body.title, query_text=body.title,
                           description=body.description, category=body.category, visibility=body.visibility,
                           delivery_mode=body.delivery_mode)
    await session.flush()
    await idem.store({"id": str(w.id)})
    return await watch_out(session, w, user)


@router.get("/{watch_id}", response_model=WatchOut)
async def get(watch_id: uuid.UUID, user: OptionalUser, session: DB) -> WatchOut:
    w = await get_watch_for_user(session, watch_id, user)
    return await watch_out(session, w, user)


@router.patch("/{watch_id}", response_model=WatchOut)
async def update(watch_id: uuid.UUID, body: WatchUpdateIn, user: CurrentUser, session: DB) -> WatchOut:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    data = body.model_dump(exclude_unset=True)
    if "visibility" in data and data["visibility"] != w.visibility:
        await community.request_visibility(session, w, user, data.pop("visibility"))
    else:
        data.pop("visibility", None)
    if data.get("title") and data["title"] != w.title and w.visibility == "public":
        w.moderation_status = "pending"  # re-moderate public text changes
    for k, v in data.items():
        if k == "category":
            w.category_slug = v
        elif k == "tags":
            w.tags = [t[:40] for t in v][:10]
        else:
            setattr(w, k, v)
    if w.visibility == "public" and w.moderation_status == "pending":
        from app.core.db import after_commit
        from app.workers.queue import Q_AGENTS, enqueue

        wid = w.id
        after_commit(session, lambda: enqueue("moderate_watch", str(wid), queue=Q_AGENTS,
                                               job_id=f"moderate:{wid}:{datetime.now(UTC):%H%M%S}"))
    await session.flush()
    return await watch_out(session, w, user)


@router.delete("/{watch_id}", status_code=204)
async def archive(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> None:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    if w.visibility != "private" and w.subscriber_count > 1:
        # others depend on it: don't pull it out from under them
        raise Conflict("Others subscribe to this public watch. Make it private first (they'll keep a copy), "
                       "or transfer it by deleting your account.")
    await set_status(session, w, "archived", "Archived by owner")
    session.add(AuditLog(actor_id=user.id, action="watch.archive", target_type="watch", target_id=str(w.id)))


@router.post("/{watch_id}/pause", response_model=WatchOut)
async def pause(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> WatchOut:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    if w.status not in ("active", "error"):
        raise Conflict(f"Watch is {w.status}")
    await set_status(session, w, "paused", "Paused by owner")
    return await watch_out(session, w, user)


@router.post("/{watch_id}/resume", response_model=WatchOut)
async def resume(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> WatchOut:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    if w.status not in ("paused", "error", "completed", "expired"):
        raise Conflict(f"Watch is {w.status}")
    await set_status(session, w, "active", None)
    await session.execute(Check.__table__.update().where(Check.watch_id == w.id).values(
        consecutive_failures=0, next_run_at=datetime.now(UTC) + timedelta(seconds=5)))
    return await watch_out(session, w, user)


@router.post("/{watch_id}/run", status_code=202, dependencies=[Depends(rate_limit("run_now", 10, 600))])
async def run_now_endpoint(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> dict[str, str]:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    if w.status not in ("active", "error"):
        raise Conflict(f"Watch is {w.status}; resume it first")
    plan = await plan_for(session, user)
    await consume(session, user.id, "run_now", "day", plan.limit("run_now_per_day"),
                  message=f"Your plan allows {plan.limit('run_now_per_day')} manual checks per day.")
    await run_now(session, w)
    return {"status": "queued", "message": "Checking now; watch the live view for progress."}


@router.post("/{watch_id}/fork", response_model=WatchOut, status_code=201)
async def fork(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> WatchOut:
    src = await get_watch_for_user(session, watch_id, user)
    plan = await plan_for(session, user)
    w = await fork_watch(session, src, user, plan)
    await session.flush()
    return await watch_out(session, w, user)


# ------------------------------------------------------------------ live state
@router.get("/{watch_id}/state", response_model=WatchStateOut)
async def state(watch_id: uuid.UUID, user: OptionalUser, session: DB) -> WatchStateOut:
    """Everything the live view needs in one call; subscribe to /v1/stream?watch=<id> for updates."""
    w = await get_watch_for_user(session, watch_id, user)
    ver = await session.get(WatchVersion, w.current_version_id) if w.current_version_id else None
    chk = (await session.execute(select(Check).where(Check.watch_id == w.id))).scalar_one_or_none()
    last_run = (await session.execute(select(Run).where(Run.watch_id == w.id).order_by(Run.started_at.desc())
                                      .limit(1))).scalar_one_or_none()
    last_alert = (await session.execute(select(Alert).where(Alert.watch_id == w.id).order_by(Alert.created_at.desc())
                                        .limit(1))).scalar_one_or_none()
    since = datetime.now(UTC) - timedelta(days=7)
    agg = (await session.execute(select(
        func.count(), func.count().filter(Run.llm_called.is_(True)),
        func.count().filter(Run.outcome == "skipped_unchanged"), func.count().filter(Run.outcome == "matched"),
        func.count().filter(Run.outcome.in_(("error", "blocked"))), func.coalesce(func.sum(Run.llm_tokens), 0),
    ).where(Run.watch_id == w.id, Run.started_at >= since))).one()
    sources = []
    is_owner = user is not None and (w.owner_id == user.id or user.role == "admin")
    if ver is not None:
        for s in ver.spec.get("sources", []):
            src = (await session.execute(select(Source).where(Source.url == s["url"]))).scalar_one_or_none()
            sources.append({
                "url": s["url"], "label": s.get("label"), "status": src.status if src else "new",
                "status_reason": src.status_reason if src else None,
                "last_fetched_at": src.last_fetched_at if src else None,
                "last_status_code": src.last_status_code if src else None,
            })
    prop = None
    if is_owner:
        p = (await session.execute(select(RefinementProposal).where(
            RefinementProposal.watch_id == w.id, RefinementProposal.status == "pending")
            .order_by(RefinementProposal.created_at.desc()).limit(1))).scalar_one_or_none()
        prop = RefinementOut.model_validate(p).model_dump(mode="json") if p else None
    runs7, llm7, skip7, match7, err7, tokens7 = agg
    return WatchStateOut(
        watch=await watch_out(session, w, user),
        current_version=VersionOut.model_validate(ver) if (ver and is_owner) else None,
        schedule={
            "enabled": chk.enabled if chk else False, "interval_seconds": chk.interval_seconds if chk else None,
            "next_run_at": chk.next_run_at if chk and chk.enabled else None,
            "last_run_at": chk.last_run_at if chk else None, "running": bool(chk and chk.lease_until and
                                                                              chk.lease_until > datetime.now(UTC)),
            "consecutive_failures": chk.consecutive_failures if chk else 0,
        },
        last_run=RunDetailOut.model_validate(last_run) if last_run else None,
        last_alert=await alert_out(session, last_alert, user) if last_alert else None,
        stats={"runs_7d": runs7, "llm_calls_7d": llm7, "skipped_without_ai_7d": skip7, "alerts_7d": match7,
               "errors_7d": err7, "llm_tokens_7d": int(tokens7),
               "ai_skip_ratio_7d": round(1 - (llm7 / runs7), 3) if runs7 else None},
        sources=sources, pending_refinement=prop,
    )


@router.get("/{watch_id}/runs", response_model=Page[RunOut])
async def runs(watch_id: uuid.UUID, user: OptionalUser, session: DB, cursor: str | None = None,
               limit: int = Query(30, ge=1, le=100), outcome: str | None = None) -> Page[RunOut]:
    w = await get_watch_for_user(session, watch_id, user)
    q = select(Run).where(Run.watch_id == w.id)
    if outcome:
        q = q.where(Run.outcome == outcome)
    if cursor:
        ts, rid = decode_cursor(cursor)
        q = q.where((Run.started_at < ts) | and_(Run.started_at == ts, Run.id < rid))
    rows = list((await session.execute(q.order_by(Run.started_at.desc(), Run.id.desc()).limit(limit + 1))).scalars())
    nxt = encode_cursor(rows[limit - 1].started_at, rows[limit - 1].id) if len(rows) > limit else None
    return Page(items=[RunOut.model_validate(r) for r in rows[:limit]], next_cursor=nxt)


@router.get("/{watch_id}/runs/{run_id}", response_model=RunDetailOut)
async def run_detail(watch_id: uuid.UUID, run_id: uuid.UUID, user: OptionalUser, session: DB) -> Run:
    w = await get_watch_for_user(session, watch_id, user)
    r = await session.get(Run, run_id)
    if r is None or r.watch_id != w.id:
        raise NotFound("Run not found")
    return r


@router.get("/{watch_id}/alerts", response_model=Page[AlertOut])
async def watch_alerts(watch_id: uuid.UUID, user: OptionalUser, session: DB, cursor: str | None = None,
                       limit: int = Query(20, ge=1, le=100)) -> Page[AlertOut]:
    w = await get_watch_for_user(session, watch_id, user)
    q = select(Alert).where(Alert.watch_id == w.id)
    if cursor:
        ts, aid = decode_cursor(cursor)
        q = q.where((Alert.created_at < ts) | and_(Alert.created_at == ts, Alert.id < aid))
    rows = list((await session.execute(q.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit + 1))).scalars())
    nxt = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return Page(items=[await alert_out(session, a, user) for a in rows[:limit]], next_cursor=nxt)


# ------------------------------------------------------------------ versions & spec
@router.get("/{watch_id}/versions", response_model=list[VersionOut])
async def versions(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> list[WatchVersion]:
    w = await get_watch_for_user(session, watch_id, user, write=True)
    return list((await session.execute(select(WatchVersion).where(WatchVersion.watch_id == w.id)
                                       .order_by(WatchVersion.version.desc()))).scalars())


@router.get("/{watch_id}/versions/diff")
async def version_diff(watch_id: uuid.UUID, user: CurrentUser, session: DB, a: int = Query(..., ge=1),
                       b: int = Query(..., ge=1)) -> dict[str, Any]:
    w = await get_watch_for_user(session, watch_id, user, write=True)
    rows = {v.version: v for v in (await session.execute(select(WatchVersion).where(
        WatchVersion.watch_id == w.id, WatchVersion.version.in_((a, b))))).scalars()}
    if a not in rows or b not in rows:
        raise NotFound("Version not found")
    return {"from": a, "to": b, "changes": spec_diff(rows[a].spec, rows[b].spec), "changelog": rows[b].changelog}


def spec_diff(old: dict[str, Any], new: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k in sorted(set(old) | set(new)):
        path = f"{prefix}.{k}" if prefix else k
        ov, nv = old.get(k), new.get(k)
        if isinstance(ov, dict) and isinstance(nv, dict):
            out.extend(spec_diff(ov, nv, path))
        elif ov != nv:
            out.append({"field": path, "from": ov, "to": nv})
    return out


@router.put("/{watch_id}/spec", response_model=VersionOut)
async def update_spec(watch_id: uuid.UUID, body: SpecUpdateIn, user: CurrentUser, session: DB) -> WatchVersion:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    spec = _validate_spec(body.spec)
    plan = await plan_for(session, user)
    v = await new_version(session, w, spec, plan=plan, created_by="user", changelog=body.changelog)
    if w.visibility == "public":
        w.moderation_status = "pending"
    return v


@router.post("/{watch_id}/versions/{version}/rollback", response_model=VersionOut)
async def rollback(watch_id: uuid.UUID, version: int, user: CurrentUser, session: DB) -> WatchVersion:
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    old = (await session.execute(select(WatchVersion).where(WatchVersion.watch_id == w.id,
                                                            WatchVersion.version == version))).scalar_one_or_none()
    if old is None:
        raise NotFound("Version not found")
    plan = await plan_for(session, user)
    return await new_version(session, w, WatchSpec.model_validate(old.spec), plan=plan, created_by="rollback",
                             changelog=f"Rolled back to version {version}")


# ------------------------------------------------------------------ self-tuning
@router.get("/{watch_id}/refinements", response_model=list[RefinementOut])
async def refinements(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> list[RefinementProposal]:
    w = await get_watch_for_user(session, watch_id, user, write=True)
    return list((await session.execute(select(RefinementProposal).where(RefinementProposal.watch_id == w.id)
                                       .order_by(RefinementProposal.created_at.desc()).limit(50))).scalars())


@router.post("/{watch_id}/refinements/{proposal_id}/{decision}", response_model=RefinementOut)
async def decide_refinement(watch_id: uuid.UUID, proposal_id: uuid.UUID, decision: str, user: CurrentUser,
                            session: DB) -> RefinementProposal:
    if decision not in ("accept", "reject"):
        raise NotFound("Unknown decision")
    w = await get_watch_for_user(session, watch_id, user, write=True, lock=True)
    p = await session.get(RefinementProposal, proposal_id)
    if p is None or p.watch_id != w.id:
        raise NotFound("Proposal not found")
    if p.status != "pending":
        raise Conflict(f"Proposal is {p.status}")
    p.decided_at = datetime.now(UTC)
    if decision == "reject":
        p.status = "rejected"
        return p
    if p.from_version_id != w.current_version_id:
        p.status = "superseded"
        raise Conflict("The watch changed since this was proposed")
    plan = await plan_for(session, user)
    v = await new_version(session, w, WatchSpec.model_validate(p.proposed_spec), plan=plan, created_by="refinement",
                          changelog="Accepted suggestion: " + "; ".join(str(c) for c in p.changes)[:1500],
                          backtest=p.backtest)
    p.status = "applied"
    p.applied_version_id = v.id
    return p


@router.post("/{watch_id}/refine", status_code=202, dependencies=[Depends(rate_limit("refine", 5, 3600))])
async def refine_now(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> dict[str, Any]:
    w = await get_watch_for_user(session, watch_id, user, write=True)
    from app.agents.refine import maybe_trigger_refinement

    started = await maybe_trigger_refinement(w.id, force=True)
    return {"started": started}


# ------------------------------------------------------------------ community
@router.post("/{watch_id}/subscribe", response_model=WatchOut, dependencies=[Depends(rate_limit("subscribe", 60, 3600))])
async def subscribe(watch_id: uuid.UUID, user: CurrentUser, session: DB,
                    body: SubscriptionPrefsIn | None = None) -> WatchOut:
    w = await get_watch_for_user(session, watch_id, user)
    await community.subscribe(session, user, w, delivery_mode=body.delivery_mode if body else None,
                              channels=list(body.channels) if body and body.channels else None)
    await session.refresh(w)
    return await watch_out(session, w, user)


@router.delete("/{watch_id}/subscribe", status_code=204)
async def unsubscribe(watch_id: uuid.UUID, user: CurrentUser, session: DB) -> None:
    if not await community.unsubscribe(session, user, watch_id):
        raise NotFound("Not subscribed")


@router.patch("/{watch_id}/subscription", response_model=dict)
async def subscription_prefs(watch_id: uuid.UUID, body: SubscriptionPrefsIn, user: CurrentUser,
                             session: DB) -> dict[str, Any]:
    sub = (await session.execute(select(Subscription).where(Subscription.watch_id == watch_id,
                                                            Subscription.user_id == user.id))).scalar_one_or_none()
    if sub is None:
        raise NotFound("Not subscribed")
    data = body.model_dump(exclude_unset=True)
    if "channels" in data and data["channels"] is not None:
        plan = await plan_for(session, user)
        if not plan.feature("per_watch_channels"):
            raise Forbidden("Per-watch channels need the Plus plan")
    for k, v in data.items():
        setattr(sub, k, v)
    return {"delivery_mode": sub.delivery_mode, "channels": sub.channels, "muted": sub.muted}


@router.post("/{watch_id}/report", dependencies=[Depends(rate_limit("report", 20, 3600))])
async def report(watch_id: uuid.UUID, body: ReportIn, user: CurrentUser, session: DB) -> dict[str, Any]:
    w = await get_watch_for_user(session, watch_id, user)
    if w.owner_id == user.id:
        raise Conflict("You can't report your own watch")
    return await community.report_watch(session, user, w, body.reason, body.detail)

