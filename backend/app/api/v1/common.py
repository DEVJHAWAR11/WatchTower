from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.models import ActionDecision, Alert, Feedback, Profile, ProposedAction
from app.schemas.api import ActionOut, AlertOut, OwnerOut
from app.services.community import SYSTEM_USER_ID


def encode_cursor(ts: datetime, id_: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{id_}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, id_ = raw.split("|", 1)
        return datetime.fromisoformat(ts), uuid.UUID(id_)
    except (ValueError, UnicodeDecodeError) as e:
        raise ValidationFailed("Invalid cursor") from e


async def owner_out(session: Any, owner_id: uuid.UUID) -> OwnerOut:
    if owner_id == SYSTEM_USER_ID:
        return OwnerOut(handle="community", display_name="Watchtower Community", is_community=True)
    p = await session.get(Profile, owner_id)
    return OwnerOut(handle=p.handle if p else None, display_name=p.display_name if p else None)


async def alert_out(session: Any, a: Alert, user: Profile | None) -> AlertOut:
    out = AlertOut.model_validate(a)
    actions = (await session.execute(select(ProposedAction).where(ProposedAction.alert_id == a.id)
                                     .order_by(ProposedAction.created_at))).scalars().all()
    decisions: dict[uuid.UUID, ActionDecision] = {}
    if user is not None and actions:
        decisions = {d.action_id: d for d in (await session.execute(select(ActionDecision).where(
            ActionDecision.user_id == user.id, ActionDecision.action_id.in_([x.id for x in actions])))).scalars()}
        fb = (await session.execute(select(Feedback.relevant).where(Feedback.alert_id == a.id,
                                                                     Feedback.user_id == user.id))).scalar_one_or_none()
        out.my_feedback = fb
    elif user is not None:
        out.my_feedback = (await session.execute(select(Feedback.relevant).where(
            Feedback.alert_id == a.id, Feedback.user_id == user.id))).scalar_one_or_none()
    out.actions = []
    for x in actions:
        ao = ActionOut.model_validate(x)
        d = decisions.get(x.id)
        if d is not None:
            ao.decision, ao.result = d.status, d.result
        out.actions.append(ao)
    if user is None:
        out.act_result = {k: v for k, v in (a.act_result or {}).items() if k != "draft_message"}
    return out
