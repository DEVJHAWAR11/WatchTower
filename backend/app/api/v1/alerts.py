"""Alert inbox, feedback (drives self-tuning), and approve/reject of proposed actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DB, CurrentUser, rate_limit
from app.api.v1.common import alert_out, decode_cursor, encode_cursor
from app.core.crypto import verify_payload
from app.core.errors import Forbidden, NotFound
from app.models import Alert, Feedback, Profile, ProposedAction, Subscription, Watch
from app.realtime.events import publish_watch
from app.schemas.api import AlertOut, FeedbackIn, Page
from app.services.actions import decide, ics_for
from app.services.watches import get_watch_for_user

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=Page[AlertOut])
async def inbox(user: CurrentUser, session: DB, cursor: str | None = None, limit: int = Query(20, ge=1, le=100),
                watch_id: uuid.UUID | None = None) -> Page[AlertOut]:
    """All alerts from watches the user owns or subscribes to, newest first."""
    q = (select(Alert).join(Subscription, and_(Subscription.watch_id == Alert.watch_id, Subscription.user_id == user.id))
         .where(Alert.created_at >= Subscription.created_at))
    if watch_id:
        q = q.where(Alert.watch_id == watch_id)
    if cursor:
        ts, aid = decode_cursor(cursor)
        q = q.where((Alert.created_at < ts) | and_(Alert.created_at == ts, Alert.id < aid))
    rows = list((await session.execute(q.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit + 1))).scalars())
    nxt = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return Page(items=[await alert_out(session, a, user) for a in rows[:limit]], next_cursor=nxt)


@router.get("/alerts/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: uuid.UUID, user: CurrentUser, session: DB) -> AlertOut:
    a = await session.get(Alert, alert_id)
    if a is None:
        raise NotFound("Alert not found")
    await get_watch_for_user(session, a.watch_id, user)
    return await alert_out(session, a, user)


async def record_feedback(session: DB, user: Profile, alert: Alert, relevant: bool, reason: str | None) -> None:
    await session.execute(pg_insert(Feedback).values(
        alert_id=alert.id, watch_id=alert.watch_id, user_id=user.id, relevant=relevant, reason=reason,
    ).on_conflict_do_update(index_elements=["alert_id", "user_id"], set_={"relevant": relevant, "reason": reason}))


@router.post("/alerts/{alert_id}/feedback", dependencies=[Depends(rate_limit("feedback", 120, 3600))])
async def feedback(alert_id: uuid.UUID, body: FeedbackIn, user: CurrentUser, session: DB) -> dict[str, object]:
    a = await session.get(Alert, alert_id)
    if a is None:
        raise NotFound("Alert not found")
    sub = await session.scalar(select(Subscription.id).where(Subscription.watch_id == a.watch_id,
                                                            Subscription.user_id == user.id))
    if not sub:
        raise NotFound("Alert not found")
    await record_feedback(session, user, a, body.relevant, body.reason)
    w = await session.get(Watch, a.watch_id)
    triggered = False
    if w is not None and (w.owner_id == user.id or w.visibility == "public"):
        from app.agents.refine import maybe_trigger_refinement

        await session.commit()
        triggered = await maybe_trigger_refinement(w.id)
    await publish_watch(a.watch_id, "feedback.recorded", {"alert_id": str(alert_id), "relevant": body.relevant})
    return {"recorded": True, "refinement_started": triggered}


@router.post("/actions/{action_id}/{decision}", dependencies=[Depends(rate_limit("actions", 60, 3600))])
async def decide_action(action_id: uuid.UUID, decision: str, user: CurrentUser, session: DB) -> dict[str, object]:
    if decision not in ("approve", "reject"):
        raise NotFound("Unknown decision")
    return await decide(session, action_id, user, decision == "approve")


@router.get("/actions/{action_id}/calendar.ics")
async def calendar(action_id: uuid.UUID, token: str, session: DB) -> Response:
    data = verify_payload(token, "ics")
    if not data or data.get("a") != str(action_id):
        raise Forbidden("Invalid or expired link")
    action = await session.get(ProposedAction, action_id)
    if action is None or action.kind != "add_to_calendar":
        raise NotFound("Not found")
    return Response(ics_for(action), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="watchtower-{action_id}.ics"'})
