"""Inbound webhooks: Telegram bot updates, Resend (Svix-signed) email events, Supabase auth hook.

All are signature/secret verified with constant-time comparison and replay windows.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DB
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.logging import get_logger
from app.core.redis import get_redis, sliding_window_allow
from app.models import Alert, AuditLog, EmailSuppression, Feedback, Profile, Subscription, TelegramLink
from app.notify.channels import DeliveryFailure, telegram_sender
from app.services import billing

router = APIRouter(tags=["webhooks"])
log = get_logger(__name__)
REPLAY_WINDOW = 300


def verify_standard_webhook(secret: str, msg_id: str, timestamp: str, signature_header: str, body: bytes) -> bool:
    """Standard Webhooks / Svix verification (used by Resend and Supabase auth hooks)."""
    if not (secret and msg_id and timestamp and signature_header):
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > REPLAY_WINDOW:
        return False
    raw_secret = secret.split(",", 1)[1] if secret.startswith("v1,") else secret
    raw_secret = raw_secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(raw_secret)
    except ValueError:
        return False
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()).decode()
    for part in signature_header.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return True
    return False


# ------------------------------------------------------------------ Telegram
@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request, session: DB,
                           x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None) -> dict[str, bool]:
    secret = get_settings().telegram_webhook_secret.get_secret_value()
    if not secret or not x_telegram_bot_api_secret_token or not hmac.compare_digest(secret, x_telegram_bot_api_secret_token):
        raise Unauthorized("bad secret")
    body = await request.body()
    if len(body) > 64 * 1024:
        return {"ok": True}
    try:
        update_ = json.loads(body)
    except ValueError:
        return {"ok": True}
    upd_id = update_.get("update_id")
    if upd_id is not None and not await get_redis().set(f"tgupd:{upd_id}", "1", nx=True, ex=86400):
        return {"ok": True}  # Telegram retried an update we already handled
    try:
        if "callback_query" in update_:
            await _tg_callback(session, update_["callback_query"])
        elif "message" in update_:
            await _tg_message(session, update_["message"])
    except DeliveryFailure as e:
        log.warning("telegram_reply_failed", error=str(e))
    return {"ok": True}


async def _tg_message(session: DB, msg: dict[str, Any]) -> None:
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = str(msg.get("text") or "").strip()
    if not chat_id or chat.get("type") != "private":
        return
    ok, _ = await sliding_window_allow(f"rl:tgchat:{chat_id}", 20, 60)
    if not ok:
        return
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""
        r = get_redis()
        uid = await r.getdel(f"tglink:{token}") if token else None
        if not uid:
            await telegram_sender.send(chat_id=chat_id, text="Hi! To get Watchtower alerts here, open Settings → "
                                                             "Notifications → Connect Telegram in the app.")
            return
        user_id = uuid.UUID(uid)
        # one chat <-> one account
        await session.execute(delete(TelegramLink).where(TelegramLink.chat_id == chat_id, TelegramLink.user_id != user_id))
        await session.execute(pg_insert(TelegramLink).values(
            user_id=user_id, chat_id=chat_id, username=str(chat.get("username") or "")[:64] or None, active=True,
        ).on_conflict_do_update(index_elements=["user_id"], set_={"chat_id": chat_id, "active": True,
                                                                  "username": str(chat.get("username") or "")[:64] or None}))
        prof = await session.get(Profile, user_id)
        if prof is not None and "telegram" not in (prof.default_channels or []):
            prof.default_channels = [*(prof.default_channels or []), "telegram"]
        session.add(AuditLog(actor_id=user_id, action="telegram.link", target_type="telegram", target_id=str(chat_id)))
        await session.commit()
        await telegram_sender.send(chat_id=chat_id, text="✅ Connected! Your Watchtower alerts will arrive here. "
                                                         "Send /stop to disconnect.")
    elif text.startswith("/stop"):
        await session.execute(update(TelegramLink).where(TelegramLink.chat_id == chat_id).values(active=False))
        await session.commit()
        await telegram_sender.send(chat_id=chat_id, text="Disconnected. You won't get alerts here anymore.")
    elif text.startswith("/help"):
        await telegram_sender.send(chat_id=chat_id, text="I send your Watchtower alerts. Tap 👍/👎 on an alert to "
                                                         "teach your watch. /stop to disconnect.")


async def _tg_callback(session: DB, cq: dict[str, Any]) -> None:
    data = str(cq.get("data") or "")
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
    cq_id = cq.get("id")
    reply = "Thanks!"
    if data.startswith("fb:") and chat_id:
        try:
            _, alert_id, rel = data.split(":", 2)
            aid = uuid.UUID(alert_id)
        except ValueError:
            return
        link = (await session.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id,
                                                                 TelegramLink.active.is_(True)))).scalar_one_or_none()
        alert = await session.get(Alert, aid)
        if link is not None and alert is not None:
            sub = await session.scalar(select(Subscription.id).where(Subscription.watch_id == alert.watch_id,
                                                                    Subscription.user_id == link.user_id))
            if sub:
                await session.execute(pg_insert(Feedback).values(
                    alert_id=aid, watch_id=alert.watch_id, user_id=link.user_id, relevant=rel == "1",
                ).on_conflict_do_update(index_elements=["alert_id", "user_id"], set_={"relevant": rel == "1"}))
                await session.commit()
                from app.agents.refine import maybe_trigger_refinement

                await maybe_trigger_refinement(alert.watch_id)
                reply = "Got it, marked useful 👍" if rel == "1" else "Got it, I'll learn from this 👎"
    if cq_id:
        await telegram_sender.call("answerCallbackQuery", {"callback_query_id": cq_id, "text": reply})


# ------------------------------------------------------------------ Resend (email events)
@router.post("/webhooks/resend")
async def resend_webhook(request: Request, session: DB,
                         svix_id: Annotated[str | None, Header()] = None,
                         svix_timestamp: Annotated[str | None, Header()] = None,
                         svix_signature: Annotated[str | None, Header()] = None) -> dict[str, bool]:
    body = await request.body()
    secret = get_settings().resend_webhook_secret.get_secret_value()
    if not verify_standard_webhook(secret, svix_id or "", svix_timestamp or "", svix_signature or "", body):
        raise Unauthorized("bad signature")
    if not await get_redis().set(f"svix:{svix_id}", "1", nx=True, ex=86400):
        return {"ok": True}
    ev = json.loads(body)
    etype = ev.get("type", "")
    data = ev.get("data") or {}
    recipients = data.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    bounce_type = str((data.get("bounce") or {}).get("type", "")).lower()
    reason = None
    if etype == "email.bounced" and bounce_type in ("", "permanent", "hard"):
        reason = "bounce"
    elif etype == "email.complained":
        reason = "complaint"
    if reason:
        for addr in recipients[:10]:
            email = str(addr).lower()[:320]
            await session.execute(pg_insert(EmailSuppression).values(email=email, reason=reason).on_conflict_do_nothing())
            if reason == "complaint":
                await session.execute(update(Profile).where(Profile.email == email).values(email_alerts_enabled=False))
    return {"ok": True}


# ------------------------------------------------------------------ Dodo Payments (subscription events)
@router.post("/webhooks/dodo")
async def dodo_webhook(request: Request, session: DB,
                       webhook_id: Annotated[str | None, Header()] = None,
                       webhook_timestamp: Annotated[str | None, Header()] = None,
                       webhook_signature: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    body = await request.body()
    secret = get_settings().dodo_webhook_secret.get_secret_value()
    if not verify_standard_webhook(secret, webhook_id or "", webhook_timestamp or "", webhook_signature or "", body):
        raise Unauthorized("bad signature")
    try:
        ev = json.loads(body)
    except ValueError:
        return {"ok": True, "result": "ignored"}
    etype = str(ev.get("type") or "")
    result = "ignored"
    if etype.startswith("subscription."):
        result = await billing.apply_subscription_event(session, etype, ev.get("data") or {})
    return {"ok": True, "result": result}


# ------------------------------------------------------------------ Supabase "before user created" auth hook
@router.post("/hooks/auth/before-user-created")
async def before_user_created(request: Request,
                              webhook_id: Annotated[str | None, Header()] = None,
                              webhook_timestamp: Annotated[str | None, Header()] = None,
                              webhook_signature: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    body = await request.body()
    secret = get_settings().auth_hook_secret.get_secret_value()
    if not verify_standard_webhook(secret, webhook_id or "", webhook_timestamp or "", webhook_signature or "", body):
        raise Unauthorized("bad signature")
    payload = json.loads(body)
    email = str((payload.get("user") or {}).get("email") or "").lower()
    ip = str((payload.get("metadata") or {}).get("ip_address") or "")
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    if domain in set(get_settings().disposable_email_domains):
        return {"error": {"http_code": 400, "message": "Please use a permanent email address."}}
    if ip:
        ok, _ = await sliding_window_allow(f"rl:hook_signup:{ip}", 5, 3600)
        if not ok:
            return {"error": {"http_code": 429, "message": "Too many sign-ups from this network. Try later."}}
    return {}
