"""Notification dispatch.

Flow: alert (after Act) -> fanout_alert (chunked over subscribers) -> one AlertDelivery row per (user, channel),
unique on (dedup_key, channel) so retries/replays can never double-send -> send_delivery jobs.

Per user: delivery mode (instant/digest), quiet hours (held until they end), hourly cap (overflow -> digest),
channel availability (falls back to email). Digests go out at each user's local digest time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.crypto import decrypt
from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models import (
    Alert,
    AlertDelivery,
    EmailSuppression,
    Profile,
    ProposedAction,
    PushSubscription,
    Reminder,
    Subscription,
    TelegramLink,
    Watch,
    WebhookEndpoint,
)
from app.notify import render
from app.notify.channels import (
    PermanentFailure,
    TransientFailure,
    email_sender,
    push_sender,
    telegram_sender,
    webhook_sender,
)
from app.observability.metrics import NOTIFY_TOTAL
from app.realtime.events import publish_user
from app.services.plans import effective_plan_id, get_plan
from app.workers.queue import Q_NOTIFY, enqueue

log = get_logger(__name__)
MAX_ATTEMPTS = 5
FANOUT_CHUNK = 500
ALL_CHANNELS = ("email", "push", "telegram", "webhook")


def user_tz(p: Profile) -> ZoneInfo:
    try:
        return ZoneInfo(p.timezone or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Kolkata")


def in_quiet_hours(p: Profile, now: datetime) -> datetime | None:
    """If `now` is inside the user's quiet hours, return when they end (UTC)."""
    if p.quiet_hours_start is None or p.quiet_hours_end is None or p.quiet_hours_start == p.quiet_hours_end:
        return None
    tz = user_tz(p)
    local = now.astimezone(tz)
    start, end = p.quiet_hours_start, p.quiet_hours_end
    t = local.time()
    inside = (start <= t < end) if start < end else (t >= start or t < end)
    if not inside:
        return None
    end_date = local.date()
    if start > end and t >= start:
        end_date = end_date + timedelta(days=1)
    return datetime.combine(end_date, end, tzinfo=tz).astimezone(UTC)


async def _available_channels(session: Any, p: Profile, wanted: list[str], plan_features: dict[str, Any]) -> list[str]:
    allowed = set(plan_features.get("channels") or ["email", "push", "telegram"])
    out: list[str] = []
    for ch in wanted:
        if ch not in allowed:
            continue
        if ch == "email":
            if p.email and p.email_alerts_enabled and not await session.get(EmailSuppression, p.email.lower()):
                out.append(ch)
        elif ch == "push":
            if push_sender.available() and await session.scalar(
                select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == p.id)
            ):
                out.append(ch)
        elif ch == "telegram":
            link = await session.get(TelegramLink, p.id)
            if link is not None and link.active and telegram_sender.available():
                out.append(ch)
        elif ch == "webhook" and plan_features.get("webhooks"):
            if await session.scalar(select(func.count()).select_from(WebhookEndpoint).where(
                    WebhookEndpoint.user_id == p.id, WebhookEndpoint.active.is_(True))):
                out.append(ch)
    if not out and "email" not in wanted and p.email and p.email_alerts_enabled:
        if not await session.get(EmailSuppression, p.email.lower()):
            out.append("email")  # never silently drop an alert: fall back to email
    return out


async def _over_hourly_cap(user_id: uuid.UUID, cap: int) -> bool:
    key = f"notif:rate:{user_id}:{datetime.now(UTC):%Y%m%d%H}"
    r = get_redis()
    n = await r.incr(key)
    if n == 1:
        await r.expire(key, 3700)
    return n > cap


# ------------------------------------------------------------------ alert fan-out
async def fanout_alert(ctx: dict[str, Any] | None, alert_id: str, after_sub_id: str | None = None) -> dict[str, Any]:
    aid = uuid.UUID(alert_id)
    to_send: list[uuid.UUID] = []
    events: list[tuple[uuid.UUID, dict[str, Any]]] = []
    now = datetime.now(UTC)
    async with session_scope() as s:
        alert = await s.get(Alert, aid)
        if alert is None:
            return {"skipped": "missing"}
        watch = await s.get(Watch, alert.watch_id)
        if watch is None:
            return {"skipped": "watch_missing"}
        q = (select(Subscription, Profile).join(Profile, Profile.id == Subscription.user_id)
             .where(Subscription.watch_id == watch.id).order_by(Subscription.id).limit(FANOUT_CHUNK))
        if after_sub_id:
            q = q.where(Subscription.id > uuid.UUID(after_sub_id))
        rows = (await s.execute(q)).all()
        for sub, prof in rows:
            if sub.muted or prof.status != "active":
                continue
            plan = await get_plan(s, effective_plan_id(prof))
            mode = sub.delivery_mode or (watch.default_delivery_mode if sub.role == "owner" else prof.default_delivery_mode)
            wanted = list(sub.channels) if (sub.channels and plan.feature("per_watch_channels")) else list(
                prof.default_channels or ["email"])
            channels = await _available_channels(s, prof, wanted, plan.features)
            if not channels:
                continue
            status, scheduled, reason = "pending", None, None
            if mode == "instant":
                quiet_end = in_quiet_hours(prof, now)
                cap = min(prof.max_alerts_per_hour or 6, plan.limit("max_alerts_per_hour"))
                if quiet_end is not None:
                    status, scheduled, reason = "held", quiet_end, "quiet hours"
                elif await _over_hourly_cap(prof.id, cap):
                    mode, reason = "digest", f"more than {cap} alerts this hour; moved to digest"
            for ch in channels:
                res = await s.execute(
                    pg_insert(AlertDelivery).values(
                        alert_id=aid, user_id=prof.id, channel=ch, kind="alert", mode=mode, status=status,
                        status_reason=reason, dedup_key=f"alert:{aid}:{prof.id}", scheduled_for=scheduled,
                    ).on_conflict_do_nothing(constraint="uq_alert_deliveries_dedup_channel").returning(AlertDelivery.id)
                )
                did = res.scalar_one_or_none()
                if did is not None and mode == "instant" and status == "pending":
                    to_send.append(did)
            events.append((prof.id, {"alert_id": alert_id, "watch_id": str(watch.id), "title": alert.title,
                                     "summary": alert.summary, "mode": mode, "held": status == "held"}))
        last_id = rows[-1][0].id if rows else None
        more = len(rows) == FANOUT_CHUNK
        if not more:
            alert.notify_status = "fanned_out"
            alert.notified_at = now
    for did in to_send:
        await enqueue("send_delivery", str(did), queue=Q_NOTIFY, job_id=f"dlv:{did}")
    for uid, data in events:
        await publish_user(uid, "alert.created", data)
    if more and last_id is not None:
        await enqueue("fanout_alert", alert_id, str(last_id), queue=Q_NOTIFY, job_id=f"fanout:{alert_id}:{last_id}")
    return {"queued": len(to_send), "more": more}


# ------------------------------------------------------------------ sending
async def send_delivery(ctx: dict[str, Any] | None, delivery_id: str) -> dict[str, Any]:
    did = uuid.UUID(delivery_id)
    async with session_scope() as s:
        d = (await s.execute(
            select(AlertDelivery).where(AlertDelivery.id == did).with_for_update(skip_locked=True)
        )).scalar_one_or_none()
        if d is None or d.status not in ("pending",):
            return {"skipped": d.status if d else "missing"}
        d.status = "sending"
        d.attempts = (d.attempts or 0) + 1
        attempt = d.attempts
    try:
        provider_id = await _deliver(did)
    except PermanentFailure as e:
        await _finish(did, "failed", str(e))
        NOTIFY_TOTAL.labels(channel=await _channel(did), status="failed").inc()
        return {"status": "failed", "error": str(e)}
    except TransientFailure as e:
        if attempt >= MAX_ATTEMPTS:
            await _finish(did, "failed", f"gave up after {attempt} attempts: {e}")
            NOTIFY_TOTAL.labels(channel=await _channel(did), status="failed").inc()
            return {"status": "failed"}
        await _finish(did, "pending", str(e))
        delay = e.retry_after or min(30 * 2 ** attempt, 3600)
        await enqueue("send_delivery", delivery_id, queue=Q_NOTIFY, job_id=f"dlv:{did}:{attempt}", defer_seconds=delay)
        NOTIFY_TOTAL.labels(channel=await _channel(did), status="retry").inc()
        return {"status": "retry", "in": delay}
    except Exception as e:
        log.exception("delivery_crashed", delivery_id=delivery_id)
        await _finish(did, "pending" if attempt < MAX_ATTEMPTS else "failed", f"internal: {type(e).__name__}")
        if attempt < MAX_ATTEMPTS:
            await enqueue("send_delivery", delivery_id, queue=Q_NOTIFY, job_id=f"dlv:{did}:{attempt}",
                          defer_seconds=60 * attempt)
        return {"status": "error"}
    await _finish(did, "sent", None, provider_id)
    ch = await _channel(did)
    NOTIFY_TOTAL.labels(channel=ch, status="sent").inc()
    async with session_scope() as s:
        d = await s.get(AlertDelivery, did)
        if d is not None:
            await publish_user(d.user_id, "delivery.sent", {"delivery_id": delivery_id, "channel": ch,
                                                              "alert_id": str(d.alert_id) if d.alert_id else None})
    return {"status": "sent"}


async def _channel(did: uuid.UUID) -> str:
    async with session_scope() as s:
        d = await s.get(AlertDelivery, did)
        return d.channel if d else "unknown"


async def _finish(did: uuid.UUID, status: str, reason: str | None, provider_id: str | None = None) -> None:
    async with session_scope() as s:
        d = await s.get(AlertDelivery, did)
        if d is None:
            return
        d.status = status
        d.status_reason = reason[:500] if reason else None
        if provider_id:
            d.provider_message_id = provider_id[:128]
        if status == "sent":
            d.sent_at = datetime.now(UTC)


async def _alert_message(s: Any, alert_id: uuid.UUID, tz: str) -> render.AlertMessage | None:
    alert = await s.get(Alert, alert_id)
    if alert is None:
        return None
    watch = await s.get(Watch, alert.watch_id)
    actions = (await s.execute(select(ProposedAction).where(ProposedAction.alert_id == alert_id))).scalars().all()
    return render.build_message(alert, watch, list(actions), tz)


async def _deliver(did: uuid.UUID) -> str:
    async with session_scope() as s:
        d = await s.get(AlertDelivery, did)
        assert d is not None
        prof = await s.get(Profile, d.user_id)
        if prof is None or prof.status != "active":
            raise PermanentFailure("user inactive")
        tz = prof.timezone or "Asia/Kolkata"
        payload = dict(d.payload or {})
        channel, kind = d.channel, d.kind
        msg = await _alert_message(s, d.alert_id, tz) if d.alert_id and kind == "alert" else None
        digest_items: list[render.AlertMessage] = []
        if kind == "digest":
            for aid in payload.get("alert_ids", [])[:50]:
                m = await _alert_message(s, uuid.UUID(aid), tz)
                if m is not None:
                    digest_items.append(m)
        email = prof.email
        push_subs = (await s.execute(select(PushSubscription).where(PushSubscription.user_id == prof.id))).scalars().all()
        tg = await s.get(TelegramLink, prof.id)
        hooks = (await s.execute(select(WebhookEndpoint).where(
            WebhookEndpoint.user_id == prof.id, WebhookEndpoint.active.is_(True)))).scalars().all()
        user_id = prof.id
        for o in [*push_subs, *hooks] + ([tg] if tg else []):
            s.expunge(o)
    if kind == "alert" and msg is None:
        raise PermanentFailure("alert no longer exists")

    if channel == "email":
        if not email:
            raise PermanentFailure("no email address")
        if kind == "alert":
            assert msg is not None
            subject, html_b, text_b, headers = render.render_email(msg, user_id)
        elif kind == "digest":
            if not digest_items:
                raise PermanentFailure("empty digest")
            subject, html_b, text_b, headers = render.render_digest_email(digest_items, user_id, payload.get("date", ""))
        else:
            subject, html_b, text_b, headers = render.render_simple_email(
                payload.get("title", "Watchtower"), payload.get("body", ""), payload.get("link"), user_id)
        try:
            return await email_sender.send(to=email, subject=subject, html_body=html_b, text_body=text_b,
                                           headers=headers, idempotency_key=str(did), tags={"kind": kind})
        except PermanentFailure:
            raise

    if channel == "push":
        if kind == "alert":
            assert msg is not None
            data = render.render_push(msg)
        elif kind == "digest":
            data = {"title": f"{len(digest_items)} updates in your digest", "body": "; ".join(
                m.title for m in digest_items[:3])[:200], "url": "/", "tag": "digest"}
        else:
            data = {"title": payload.get("title", "Watchtower")[:80], "body": payload.get("body", "")[:200],
                    "url": payload.get("link") or "/", "tag": payload.get("key", "system")}
        sent = 0
        last_err: Exception | None = None
        for sub in push_subs:
            try:
                await push_sender.send(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth, payload=data)
                sent += 1
                await _push_result(sub.id, ok=True)
            except PermanentFailure as e:
                last_err = e
                await _push_result(sub.id, ok=False, remove=True)
            except TransientFailure as e:
                last_err = e
                await _push_result(sub.id, ok=False)
        if sent:
            return f"push:{sent}"
        if isinstance(last_err, TransientFailure):
            raise last_err
        raise PermanentFailure(str(last_err) if last_err else "no push subscriptions")

    if channel == "telegram":
        if tg is None or not tg.active:
            raise PermanentFailure("telegram not linked")
        if kind == "alert":
            assert msg is not None
            text = render.render_telegram(msg)
            buttons = [[{"text": "Open", "url": msg.app_url}, {"text": "Source", "url": msg.source_url}],
                       [{"text": "👍 Relevant", "callback_data": f"fb:{msg.alert_id}:1"},
                        {"text": "👎 Not relevant", "callback_data": f"fb:{msg.alert_id}:0"}]]
        elif kind == "digest":
            import html as _h

            text = "<b>Your digest</b>\n\n" + "\n\n".join(
                f"• <b>{_h.escape(m.title)}</b>\n{_h.escape(m.summary[:200])}" for m in digest_items[:15])
            buttons = None
        else:
            import html as _h

            text = f"<b>{_h.escape(payload.get('title', ''))}</b>\n\n{_h.escape(payload.get('body', ''))}"
            buttons = None
        try:
            return await telegram_sender.send(chat_id=tg.chat_id, text=text, buttons=buttons)
        except PermanentFailure:
            async with session_scope() as s:
                link = await s.get(TelegramLink, user_id)
                if link is not None:
                    link.active = False  # user blocked the bot or chat is gone
            raise

    if channel == "webhook":
        if not hooks:
            raise PermanentFailure("no active webhook")
        body = render.render_webhook(msg) if (kind == "alert" and msg) else {"type": kind, **payload}
        ok = 0
        err: Exception | None = None
        for h in hooks:
            secret = decrypt(h.secret_encrypted) or ""
            try:
                await webhook_sender.send(url=h.url, secret=secret, payload=body, delivery_id=str(did))
                ok += 1
                await _hook_result(h.id, ok=True)
            except (PermanentFailure, TransientFailure) as e:
                err = e
                await _hook_result(h.id, ok=False)
        if ok:
            return f"webhook:{ok}"
        if isinstance(err, PermanentFailure):
            raise err
        raise TransientFailure(str(err) if err else "webhook failed")
    raise PermanentFailure(f"unknown channel {channel}")


async def _push_result(sub_id: uuid.UUID, *, ok: bool, remove: bool = False) -> None:
    async with session_scope() as s:
        sub = await s.get(PushSubscription, sub_id)
        if sub is None:
            return
        if remove:
            await s.delete(sub)
        elif ok:
            sub.failure_count = 0
            sub.last_success_at = datetime.now(UTC)
        else:
            sub.failure_count = (sub.failure_count or 0) + 1


async def _hook_result(hook_id: uuid.UUID, *, ok: bool) -> None:
    async with session_scope() as s:
        h = await s.get(WebhookEndpoint, hook_id)
        if h is None:
            return
        h.failure_count = 0 if ok else (h.failure_count or 0) + 1
        if h.failure_count >= 20:
            h.active = False


# ------------------------------------------------------------------ system notifications & reminders
async def queue_system_notification(user_id: uuid.UUID, *, key: str, title: str, body: str,
                                    link: str | None = None, kind: str = "system") -> int:
    queued: list[uuid.UUID] = []
    async with session_scope() as s:
        prof = await s.get(Profile, user_id)
        if prof is None or prof.status != "active":
            return 0
        plan = await get_plan(s, effective_plan_id(prof))
        channels = await _available_channels(s, prof, list(prof.default_channels or ["email"]), plan.features)
        quiet_end = in_quiet_hours(prof, datetime.now(UTC))
        for ch in channels:
            if ch == "webhook" and kind != "system":
                continue
            res = await s.execute(pg_insert(AlertDelivery).values(
                alert_id=None, user_id=user_id, channel=ch, kind=kind, mode="instant",
                status="held" if quiet_end else "pending", scheduled_for=quiet_end, dedup_key=f"{kind}:{key}"[:128],
                payload={"title": title[:200], "body": body[:2000], "link": link, "key": key[:64]},
            ).on_conflict_do_nothing(constraint="uq_alert_deliveries_dedup_channel").returning(AlertDelivery.id))
            did = res.scalar_one_or_none()
            if did and not quiet_end:
                queued.append(did)
    for did in queued:
        await enqueue("send_delivery", str(did), queue=Q_NOTIFY, job_id=f"dlv:{did}")
    await publish_user(user_id, "notification", {"title": title, "body": body[:300], "link": link})
    return len(queued)


async def send_due_reminders(ctx: dict[str, Any] | None = None) -> int:
    now = datetime.now(UTC)
    async with session_scope() as s:
        rows = (await s.execute(
            select(Reminder).where(Reminder.status == "pending", Reminder.remind_at <= now)
            .order_by(Reminder.remind_at).limit(500).with_for_update(skip_locked=True)
        )).scalars().all()
        due = [(r.id, r.user_id, r.message, r.alert_id) for r in rows]
        for r in rows:
            r.status = "sent"
    for rid, uid, message, alert_id in due:
        await queue_system_notification(uid, key=f"reminder:{rid}", title="⏰ Reminder", body=message,
                                        link=f"/alerts/{alert_id}" if alert_id else None, kind="reminder")
    return len(due)


async def release_held(ctx: dict[str, Any] | None = None) -> int:
    async with session_scope() as s:
        ids = (await s.execute(
            update(AlertDelivery).where(AlertDelivery.status == "held", AlertDelivery.scheduled_for <= func.now())
            .values(status="pending", status_reason="released after quiet hours").returning(AlertDelivery.id)
        )).scalars().all()
    for did in ids:
        await enqueue("send_delivery", str(did), queue=Q_NOTIFY, job_id=f"dlv:{did}:rel")
    return len(ids)


# ------------------------------------------------------------------ digests
async def run_digests(ctx: dict[str, Any] | None = None, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    sent = 0
    async with session_scope() as s:
        user_ids = (await s.execute(
            select(AlertDelivery.user_id).where(AlertDelivery.status == "pending", AlertDelivery.mode == "digest",
                                                AlertDelivery.kind == "alert").distinct().limit(5000)
        )).scalars().all()
    for uid in user_ids:
        try:
            sent += await _digest_for_user(uid, now)
        except Exception:
            log.exception("digest_failed", user_id=str(uid))
    return sent


def _digest_due(p: Profile, now: datetime) -> tuple[bool, date]:
    tz = user_tz(p)
    local = now.astimezone(tz)
    digest_t = p.digest_time or time(8, 0)
    last = p.last_digest_at.astimezone(tz).date() if p.last_digest_at else None
    due = local.time() >= digest_t and last != local.date()
    return due, local.date()


async def _digest_for_user(uid: uuid.UUID, now: datetime) -> int:
    new_ids: list[uuid.UUID] = []
    async with session_scope() as s:
        prof = await s.get(Profile, uid, with_for_update=True)
        if prof is None or prof.status != "active":
            return 0
        due, local_day = _digest_due(prof, now)
        if not due:
            return 0
        rows = (await s.execute(
            select(AlertDelivery).where(and_(AlertDelivery.user_id == uid, AlertDelivery.status == "pending",
                                             AlertDelivery.mode == "digest", AlertDelivery.kind == "alert"))
            .order_by(AlertDelivery.created_at).limit(500)
        )).scalars().all()
        if not rows:
            return 0
        by_channel: dict[str, list[str]] = {}
        for d in rows:
            by_channel.setdefault(d.channel, [])
            if str(d.alert_id) not in by_channel[d.channel]:
                by_channel[d.channel].append(str(d.alert_id))
            d.status = "digested"
        label = local_day.strftime("%d %b %Y")
        for ch, alert_ids in by_channel.items():
            res = await s.execute(pg_insert(AlertDelivery).values(
                alert_id=None, user_id=uid, channel=ch, kind="digest", mode="instant", status="pending",
                dedup_key=f"digest:{uid}:{local_day.isoformat()}", payload={"alert_ids": alert_ids, "date": label},
            ).on_conflict_do_nothing(constraint="uq_alert_deliveries_dedup_channel").returning(AlertDelivery.id))
            did = res.scalar_one_or_none()
            if did:
                new_ids.append(did)
        prof.last_digest_at = now
    for did in new_ids:
        await enqueue("send_delivery", str(did), queue=Q_NOTIFY, job_id=f"dlv:{did}")
    return len(new_ids)
