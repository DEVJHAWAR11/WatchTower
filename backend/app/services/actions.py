"""Approve / reject proposed actions. Every action is allowlisted and only ever affects the approving user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import sign_payload
from app.core.errors import AppError, Forbidden, NotFound
from app.models import (
    ActionDecision,
    Alert,
    Profile,
    ProposedAction,
    Reminder,
    Subscription,
    Watch,
    WatchVersion,
)
from app.schemas.spec import WatchSpec

ALLOWED_KINDS = {"add_to_calendar", "set_reminder", "open_link", "draft_email", "create_followup_watch",
                 "adjust_threshold"}


class ActionExpired(AppError):
    status_code = 410
    code = "action_expired"


async def load_action_for_user(session: AsyncSession, action_id: uuid.UUID, user: Profile) -> tuple[ProposedAction, Alert, Watch]:
    action = await session.get(ProposedAction, action_id)
    if action is None:
        raise NotFound("Action not found")
    alert = await session.get(Alert, action.alert_id)
    watch = await session.get(Watch, alert.watch_id) if alert else None
    if alert is None or watch is None:
        raise NotFound("Action not found")
    sub = await session.scalar(select(Subscription.id).where(Subscription.watch_id == watch.id,
                                                            Subscription.user_id == user.id))
    if not sub and watch.owner_id != user.id:
        raise NotFound("Action not found")
    if action.owner_only and watch.owner_id != user.id:
        raise Forbidden("Only the watch owner can approve this action")
    return action, alert, watch


def ics_for(action: ProposedAction) -> str:
    p = action.payload
    start = datetime.fromisoformat(p["start"]).astimezone(UTC)

    def esc(v: str) -> str:
        return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")[:900]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    local = datetime.fromisoformat(p["start"])
    if (local.hour, local.minute, local.second) == (0, 0, 0):
        # date-only deadline: an all-day event on that local date (not a midnight-UTC instant)
        day = local.date()
        when = [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
    else:
        dt = start.strftime("%Y%m%dT%H%M%SZ")
        when = [f"DTSTART:{dt}", f"DTEND:{dt}"]
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Watchtower//Alerts//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
        f"UID:{action.id}@watchtower", f"DTSTAMP:{stamp}", *when,
        f"SUMMARY:{esc(p.get('title', 'Deadline'))}", f"DESCRIPTION:{esc(p.get('url', ''))}",
        f"URL:{esc(p.get('url', ''))}", "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
        f"DESCRIPTION:{esc(p.get('title', 'Deadline'))}", "END:VALARM", "END:VEVENT", "END:VCALENDAR", "",
    ])


async def decide(session: AsyncSession, action_id: uuid.UUID, user: Profile, approve: bool) -> dict[str, Any]:
    action, alert, watch = await load_action_for_user(session, action_id, user)
    existing = await session.get(ActionDecision, (action.id, user.id))
    if existing is not None:
        return {"status": existing.status, "result": existing.result, "idempotent": True}
    if action.kind not in ALLOWED_KINDS:
        raise Forbidden("This action type is not allowed")
    if action.expires_at and action.expires_at < datetime.now(UTC):
        raise ActionExpired("This action has expired")
    if not approve:
        session.add(ActionDecision(action_id=action.id, user_id=user.id, status="rejected", result={}))
        return {"status": "rejected", "result": {}}
    result = await _execute(session, action, alert, watch, user)
    session.add(ActionDecision(action_id=action.id, user_id=user.id, status="executed", result=result))
    return {"status": "executed", "result": result}


async def _execute(session: AsyncSession, action: ProposedAction, alert: Alert, watch: Watch,
                   user: Profile) -> dict[str, Any]:
    p = action.payload or {}
    base = get_settings().public_base_url.rstrip("/")
    if action.kind == "add_to_calendar":
        token = sign_payload({"a": str(action.id), "u": str(user.id)}, "ics", ttl_seconds=90 * 24 * 3600)
        return {"ics_url": f"{base}/v1/actions/{action.id}/calendar.ics?token={token}"}
    if action.kind == "set_reminder":
        remind_at = datetime.fromisoformat(p["remind_at"])
        r = Reminder(user_id=user.id, alert_id=alert.id, remind_at=max(remind_at, datetime.now(UTC)),
                     message=str(p.get("message", ""))[:500])
        session.add(r)
        await session.flush()
        return {"reminder_id": str(r.id), "remind_at": r.remind_at.isoformat()}
    if action.kind == "open_link":
        url = str(p.get("url", ""))
        if not url.startswith(("https://", "http://")):
            raise Forbidden("Invalid link")
        return {"url": url}
    if action.kind == "draft_email":
        from app.notify.dispatch import queue_system_notification

        await session.flush()
        n = await queue_system_notification(
            user.id, key=f"draft:{action.id}:{user.id}", title=str(p.get("subject", "Your draft"))[:150],
            body=str(p.get("body", ""))[:4000], link=f"/alerts/{alert.id}",
        )
        return {"sent": n > 0, "to": "your notification channels"}
    if action.kind == "create_followup_watch":
        from app.services.intake import start_intake

        session_id = await start_intake(session, user, str(p.get("query", ""))[:300], origin=f"followup:{alert.id}")
        return {"intake_session_id": str(session_id)}
    if action.kind == "adjust_threshold":
        if watch.owner_id != user.id:
            raise Forbidden("Only the watch owner can change its threshold")
        from app.services.plans import plan_for
        from app.services.watches import new_version

        ver = await session.get(WatchVersion, watch.current_version_id)
        spec = WatchSpec.model_validate(ver.spec)
        data = spec.model_dump()
        changed = False
        for pred in data["predicates"]:
            if pred["type"] == "price_below":
                pred["threshold"] = float(p["threshold"])
                changed = True
        if not changed:
            data["predicates"].append({"type": "price_below", "threshold": float(p["threshold"])})
            data["predicate_mode"] = "decide" if data["predicate_mode"] == "none" else data["predicate_mode"]
        data["condition"] = f"{spec.condition} (only below ₹{float(p['threshold']):,.0f})"[:600]
        plan = await plan_for(session, user)
        v = await new_version(session, watch, WatchSpec.model_validate(data), plan=plan, created_by="user",
                              changelog=f"Threshold lowered to ₹{float(p['threshold']):,.0f} from an alert action")
        watch.eval_state = {}
        return {"version": v.version}
    raise Forbidden("Unsupported action")
