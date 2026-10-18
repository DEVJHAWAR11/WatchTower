"""Notification channel management: email status, Web Push subscriptions, Telegram linking, webhooks, tests."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DB, CurrentUser, rate_limit
from app.core.config import get_settings
from app.core.crypto import encrypt
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.redis import get_redis
from app.fetch.ssrf import SSRFBlocked, resolve_public, validate_url
from app.models import EmailSuppression, PushSubscription, TelegramLink, WebhookEndpoint
from app.notify.channels import push_endpoint_allowed, push_sender, telegram_sender
from app.notify.dispatch import queue_system_notification
from app.schemas.api import ChannelsOut, PushSubscribeIn, WebhookIn
from app.services.plans import plan_for

router = APIRouter(prefix="/notifications", tags=["notifications"])
TG_LINK_TTL = 600


@router.get("/channels", response_model=ChannelsOut)
async def channels(user: CurrentUser, session: DB) -> ChannelsOut:
    plan = await plan_for(session, user)
    suppressed = bool(user.email and await session.get(EmailSuppression, user.email.lower()))
    n_push = await session.scalar(select(func.count()).select_from(PushSubscription).where(
        PushSubscription.user_id == user.id))
    tg = await session.get(TelegramLink, user.id)
    hooks = (await session.execute(select(WebhookEndpoint).where(WebhookEndpoint.user_id == user.id))).scalars().all()
    allowed = set(plan.feature("channels") or [])
    return ChannelsOut(
        email={"address": user.email, "enabled": user.email_alerts_enabled and not suppressed, "suppressed": suppressed,
               "verified": user.email_verified},
        push={"available": push_sender.available(), "devices": int(n_push or 0),
              "vapid_public_key": get_settings().vapid_public_key or None},
        telegram={"available": telegram_sender.available() and "telegram" in allowed,
                  "linked": bool(tg and tg.active), "username": tg.username if tg else None},
        webhook={"available": bool(plan.feature("webhooks")),
                 "endpoints": [{"id": str(h.id), "url": h.url, "active": h.active, "failures": h.failure_count}
                               for h in hooks]},
    )


@router.post("/push", status_code=201, dependencies=[Depends(rate_limit("push_sub", 20, 3600))])
async def push_subscribe(body: PushSubscribeIn, user: CurrentUser, session: DB) -> dict[str, Any]:
    if not push_endpoint_allowed(body.endpoint):
        raise ValidationFailed("Unsupported push service endpoint")
    n = await session.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user.id))
    if (n or 0) >= 10:
        raise Conflict("Too many devices registered; remove one first")
    await session.execute(pg_insert(PushSubscription).values(
        user_id=user.id, endpoint=body.endpoint, p256dh=body.keys["p256dh"], auth=body.keys["auth"],
        user_agent=body.user_agent,
    ).on_conflict_do_update(index_elements=["endpoint"], set_={
        "user_id": user.id, "p256dh": body.keys["p256dh"], "auth": body.keys["auth"], "failure_count": 0}))
    if "push" not in (user.default_channels or []):
        user.default_channels = [*(user.default_channels or []), "push"]
    return {"subscribed": True}


@router.delete("/push", status_code=204)
async def push_unsubscribe(user: CurrentUser, session: DB, endpoint: str = Query(..., max_length=2048)) -> None:
    await session.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id,
                                                         PushSubscription.endpoint == endpoint))


@router.post("/telegram/link", dependencies=[Depends(rate_limit("tg_link", 10, 3600))])
async def telegram_link(user: CurrentUser, session: DB) -> dict[str, Any]:
    plan = await plan_for(session, user)
    if "telegram" not in (plan.feature("channels") or []) or not telegram_sender.available():
        raise Forbidden("Telegram alerts are not available")
    token = secrets.token_urlsafe(24)[:32]
    await get_redis().set(f"tglink:{token}", str(user.id), ex=TG_LINK_TTL)
    bot = get_settings().telegram_bot_username
    return {"deep_link": f"https://t.me/{bot}?start={token}", "expires_in": TG_LINK_TTL,
            "instructions": "Open the link and press Start in Telegram."}


@router.delete("/telegram", status_code=204)
async def telegram_unlink(user: CurrentUser, session: DB) -> None:
    await session.execute(delete(TelegramLink).where(TelegramLink.user_id == user.id))
    user.default_channels = [c for c in (user.default_channels or []) if c != "telegram"] or ["email"]


@router.post("/webhooks", status_code=201, dependencies=[Depends(rate_limit("webhook_create", 10, 3600))])
async def create_webhook(body: WebhookIn, user: CurrentUser, session: DB) -> dict[str, Any]:
    plan = await plan_for(session, user)
    if not plan.feature("webhooks"):
        raise Forbidden("Webhooks are available on the Pro plan")
    try:
        v = validate_url(body.url)
        if v.scheme != "https":
            raise ValidationFailed("Webhook URLs must use https")
        await resolve_public(v.host, v.port)
    except SSRFBlocked as e:
        raise ValidationFailed(f"Webhook URL not allowed ({e.reason})") from e
    n = await session.scalar(select(func.count()).select_from(WebhookEndpoint).where(WebhookEndpoint.user_id == user.id))
    if (n or 0) >= 5:
        raise Conflict("At most 5 webhook endpoints")
    secret = "whsec_" + secrets.token_urlsafe(32)
    row = WebhookEndpoint(user_id=user.id, url=body.url, secret_encrypted=encrypt(secret))
    session.add(row)
    await session.flush()
    return {"id": str(row.id), "url": row.url, "secret": secret,
            "note": "Verify X-Watchtower-Signature (t=..,v1=HMAC-SHA256(secret, f'{t}.{body}')). Secret shown once."}


@router.delete("/webhooks/{hook_id}", status_code=204)
async def delete_webhook(hook_id: uuid.UUID, user: CurrentUser, session: DB) -> None:
    res = await session.execute(delete(WebhookEndpoint).where(WebhookEndpoint.id == hook_id,
                                                              WebhookEndpoint.user_id == user.id)
                                .returning(WebhookEndpoint.id))
    if res.scalar_one_or_none() is None:
        raise NotFound("Webhook not found")


@router.post("/test", dependencies=[Depends(rate_limit("notif_test", 5, 3600))])
async def test_notification(user: CurrentUser, session: DB) -> dict[str, Any]:
    await session.commit()
    n = await queue_system_notification(user.id, key=f"test:{user.id}:{secrets.token_hex(4)}",
                                        title="Watchtower test notification",
                                        body="If you can read this, alerts will reach you here.", link="/settings")
    return {"queued": n}
