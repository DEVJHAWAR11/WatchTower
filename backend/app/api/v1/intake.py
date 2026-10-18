"""Conversational watch creation. Progress also streams over SSE as `intake.updated` events."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import DB, CurrentUser, Idempotency, idempotency, rate_limit
from app.models import IntakeSession
from app.schemas.api import IntakeAnswerIn, IntakeConfirmIn, IntakeOut, IntakeStartIn
from app.services.intake import cancel_session, get_session, resume_intake, start_intake

router = APIRouter(prefix="/intake", tags=["intake"])


@router.post("", response_model=IntakeOut, status_code=202, dependencies=[Depends(rate_limit("intake", 20, 3600))])
async def start(body: IntakeStartIn, user: CurrentUser, session: DB,
                idem: Idempotency = Depends(idempotency)) -> IntakeSession:
    if (cached := await idem.cached()) is not None:
        return await get_session(session, user, uuid.UUID(cached["id"]))
    sid = await start_intake(session, user, body.query)
    row = await get_session(session, user, sid)
    await idem.store({"id": str(sid)})
    return row


@router.get("/{session_id}", response_model=IntakeOut)
async def get(session_id: uuid.UUID, user: CurrentUser, session: DB) -> IntakeSession:
    return await get_session(session, user, session_id)


@router.post("/{session_id}/answer", response_model=IntakeOut, status_code=202,
             dependencies=[Depends(rate_limit("intake_answer", 30, 3600))])
async def answer(session_id: uuid.UUID, body: IntakeAnswerIn, user: CurrentUser, session: DB) -> IntakeSession:
    return await resume_intake(session, user, session_id, {"answers": body.answers})


@router.post("/{session_id}/confirm", response_model=IntakeOut, status_code=202,
             dependencies=[Depends(rate_limit("intake_confirm", 30, 3600))])
async def confirm(session_id: uuid.UUID, body: IntakeConfirmIn, user: CurrentUser, session: DB) -> IntakeSession:
    edits = body.edits.model_dump(exclude_none=True) if body.edits else {}
    return await resume_intake(session, user, session_id, {"confirm": body.confirm, "edits": edits})


@router.post("/{session_id}/cancel", response_model=IntakeOut)
async def cancel(session_id: uuid.UUID, user: CurrentUser, session: DB) -> IntakeSession:
    return await cancel_session(session, user, session_id)
