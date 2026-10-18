import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from datetime import time as dtime

from httpx import Response
from sqlalchemy import select, update

from app.core.db import session_scope
from app.core.redis import get_redis
from app.models import Alert, AlertDelivery, EmailSuppression, Profile, PushSubscription, TelegramLink
from app.notify import dispatch
from app.notify.channels import PermanentFailure, push_endpoint_allowed, webhook_signature
from tests.conftest import drain, emails
from tests.helpers import make_watch


async def make_alert(owner, site, title="Result declared", key="k1") -> uuid.UUID:  # noqa: ANN001
    url = site.set("gov.test", f"/{key}", "<html><body>x</body></html>")
    wid = await make_watch(owner, {"sources": [{"url": url}], "condition": "something happens"}, title="Gov watch")
    async with session_scope() as s:
        a = Alert(watch_id=wid, fingerprint=key, title=title, summary="It happened <b>now</b>", source_url=url,
                  act_status="completed", act_result={"headline": title, "what_happened": "It happened <script>x</script>"})
        s.add(a)
        await s.flush()
        return a.id


async def deliveries(user_id: uuid.UUID) -> list[AlertDelivery]:
    async with session_scope() as s:
        return list((await s.execute(select(AlertDelivery).where(AlertDelivery.user_id == user_id)
                                     .order_by(AlertDelivery.created_at))).scalars())


async def test_instant_email_escaped_and_single(make_user, site) -> None:  # noqa: ANN001
    u = await make_user(email="a@example.com")
    aid = await make_alert(u, site, title="<img src=x onerror=alert(1)>")
    await dispatch.fanout_alert({}, str(aid))
    await drain(("notify",))
    m = await emails()
    assert len(m) == 1
    assert "<img src=x" not in m[0]["html"] and "&lt;img src=x" in m[0]["html"]
    assert "<script>" not in m[0]["html"]


async def test_quiet_hours_hold_then_release(make_user, site) -> None:  # noqa: ANN001
    now_ist = datetime.now(UTC).astimezone(dispatch.ZoneInfo("Asia/Kolkata"))
    start = (now_ist - timedelta(hours=1)).time().replace(second=0, microsecond=0)
    end = (now_ist + timedelta(hours=1)).time().replace(second=0, microsecond=0)
    u = await make_user(quiet_hours_start=start, quiet_hours_end=end)
    aid = await make_alert(u, site)
    await dispatch.fanout_alert({}, str(aid))
    await drain(("notify",))
    d = await deliveries(u.id)
    assert d[0].status == "held" and d[0].scheduled_for > datetime.now(UTC) and await emails() == []
    async with session_scope() as s:
        await s.execute(update(AlertDelivery).values(scheduled_for=datetime.now(UTC) - timedelta(seconds=1)))
    assert await dispatch.release_held({}) == 1
    await drain(("notify",))
    assert len(await emails()) == 1


def test_quiet_hours_window_math() -> None:
    p = Profile(timezone="Asia/Kolkata", quiet_hours_start=dtime(23, 0), quiet_hours_end=dtime(7, 0))
    ist = dispatch.ZoneInfo("Asia/Kolkata")
    late = datetime(2026, 10, 18, 23, 30, tzinfo=ist).astimezone(UTC)
    early = datetime(2026, 10, 19, 6, 0, tzinfo=ist).astimezone(UTC)
    day = datetime(2026, 10, 19, 12, 0, tzinfo=ist).astimezone(UTC)
    assert dispatch.in_quiet_hours(p, late) == datetime(2026, 10, 19, 7, 0, tzinfo=ist).astimezone(UTC)
    assert dispatch.in_quiet_hours(p, early) == datetime(2026, 10, 19, 7, 0, tzinfo=ist).astimezone(UTC)
    assert dispatch.in_quiet_hours(p, day) is None


async def test_hourly_cap_overflows_to_digest(make_user, site) -> None:  # noqa: ANN001
    u = await make_user(max_alerts_per_hour=1, digest_time=dtime(0, 0))
    a1 = await make_alert(u, site, "First", "k1")
    a2 = await make_alert(u, site, "Second", "k2")
    a3 = await make_alert(u, site, "Third", "k3")
    for a in (a1, a2, a3):
        await dispatch.fanout_alert({}, str(a))
    await drain(("notify",))
    d = await deliveries(u.id)
    assert [x.mode for x in d] == ["instant", "digest", "digest"]
    assert len(await emails()) == 1
    sent = await dispatch.run_digests({})
    assert sent == 1
    await drain(("notify",))
    m = await emails()
    assert len(m) == 2 and "digest" in m[0]["subject"].lower() and "Second" in m[0]["text"] and "Third" in m[0]["text"]
    assert await dispatch.run_digests({}) == 0  # once per day
    assert {x.status for x in await deliveries(u.id) if x.kind == "alert" and x.mode == "digest"} == {"digested"}


async def test_digest_waits_for_users_local_time(make_user, site) -> None:  # noqa: ANN001
    u = await make_user(default_delivery_mode="digest", digest_time=dtime(8, 0), timezone="Asia/Kolkata")
    aid = await make_alert(u, site)
    async with session_scope() as s:
        await s.execute(update(Profile).where(Profile.id == u.id).values(default_delivery_mode="digest"))
        from app.models import Subscription, Watch

        await s.execute(update(Watch).values(default_delivery_mode="digest"))
        _ = Subscription
    await dispatch.fanout_alert({}, str(aid))
    ist = dispatch.ZoneInfo("Asia/Kolkata")
    before = datetime.now(UTC).astimezone(ist).replace(hour=7, minute=59).astimezone(UTC)
    after = before + timedelta(minutes=2)
    assert await dispatch.run_digests({}, now=before) == 0
    assert await dispatch.run_digests({}, now=after) == 1


async def test_telegram_link_send_and_block(client, auth, make_user, site, respx_mock) -> None:  # noqa: ANN001
    u = await make_user(default_channels=["telegram"])
    sent: list[dict] = []
    blocked = {"on": False}

    def tg(request):  # noqa: ANN001, ANN202
        body = json.loads(request.content)
        if blocked["on"] and request.url.path.endswith("/sendMessage"):
            return Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
        sent.append(body)
        return Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

    respx_mock.post(url__regex=r"https://api\.telegram\.org/bot123:abc/.*").mock(side_effect=tg)
    link = (await client.post("/v1/notifications/telegram/link", headers=auth(u))).json()
    token = link["deep_link"].split("start=")[1]
    hdr = {"X-Telegram-Bot-Api-Secret-Token": "tg-secret"}
    assert (await client.post("/v1/webhooks/telegram", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"})).status_code == 401
    upd = {"update_id": 1, "message": {"chat": {"id": 555, "type": "private", "username": "asha"}, "text": f"/start {token}"}}
    assert (await client.post("/v1/webhooks/telegram", json=upd, headers=hdr)).status_code == 200
    assert (await client.post("/v1/webhooks/telegram", json=upd, headers=hdr)).status_code == 200  # replay ignored
    async with session_scope() as s:
        tl = await s.get(TelegramLink, u.id)
        assert tl.chat_id == 555 and tl.active
    assert len(sent) == 1 and "Connected" in sent[0]["text"]
    aid = await make_alert(u, site, title="Result <out> & more")
    await dispatch.fanout_alert({}, str(aid))
    await drain(("notify",))
    msg = sent[-1]
    assert msg["chat_id"] == 555 and msg["parse_mode"] == "HTML" and "Result &lt;out&gt; &amp; more" in msg["text"]
    assert msg["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == f"fb:{aid}:1"
    # feedback button from Telegram
    cb = {"update_id": 2, "callback_query": {"id": "q1", "data": f"fb:{aid}:0", "message": {"chat": {"id": 555}}}}
    assert (await client.post("/v1/webhooks/telegram", json=cb, headers=hdr)).status_code == 200
    from app.models import Feedback

    async with session_scope() as s:
        fb = (await s.execute(select(Feedback))).scalar_one()
        assert fb.relevant is False and fb.user_id == u.id
    # user blocks the bot -> link deactivated, delivery failed (not retried forever)
    blocked["on"] = True
    a2 = await make_alert(u, site, key="k9")
    await dispatch.fanout_alert({}, str(a2))
    await drain(("notify",))
    async with session_scope() as s:
        assert (await s.get(TelegramLink, u.id)).active is False


async def test_push_endpoint_allowlist_and_expiry(client, auth, make_user, site, monkeypatch) -> None:  # noqa: ANN001
    assert push_endpoint_allowed("https://fcm.googleapis.com/fcm/send/abc")
    assert push_endpoint_allowed("https://updates.push.services.mozilla.com/wpush/v2/x")
    assert not push_endpoint_allowed("http://fcm.googleapis.com/x")
    assert not push_endpoint_allowed("https://169.254.169.254/latest")
    assert not push_endpoint_allowed("https://fcm.googleapis.com.evil.com/x")
    u = await make_user()
    bad = await client.post("/v1/notifications/push", headers=auth(u),
                            json={"endpoint": "https://evil.example/hook", "keys": {"p256dh": "k", "auth": "a"}})
    assert bad.status_code == 422
    ok = await client.post("/v1/notifications/push", headers=auth(u),
                           json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}})
    assert ok.status_code == 201
    from app.notify import channels

    monkeypatch.setattr(channels.push_sender, "available", lambda: True)
    calls = []

    async def fake_send(**kw):  # noqa: ANN003, ANN202
        calls.append(kw)
        raise PermanentFailure("push subscription expired")

    monkeypatch.setattr(channels.push_sender, "send", fake_send)
    async with session_scope() as s:
        await s.execute(update(Profile).where(Profile.id == u.id).values(default_channels=["push"]))
    aid = await make_alert(u, site)
    await dispatch.fanout_alert({}, str(aid))
    await drain(("notify",))
    assert calls and calls[0]["payload"]["url"].endswith(str(aid))
    async with session_scope() as s:
        assert (await s.execute(select(PushSubscription))).first() is None  # expired subscription cleaned up


async def test_webhook_channel_signed_and_ssrf_checked(client, auth, make_user, site, monkeypatch) -> None:  # noqa: ANN001
    u = await make_user(plan="pro")
    r = await client.post("/v1/notifications/webhooks", headers=auth(u), json={"url": "https://rebind.example.com/h"})
    assert r.status_code == 422
    r = await client.post("/v1/notifications/webhooks", headers=auth(u), json={"url": "http://public.example.com/h"})
    assert r.status_code == 422  # https only
    r = await client.post("/v1/notifications/webhooks", headers=auth(u), json={"url": "https://public.example.com/h"})
    assert r.status_code == 201
    secret = r.json()["secret"]
    free = await make_user()
    assert (await client.post("/v1/notifications/webhooks", headers=auth(free),
                              json={"url": "https://public.example.com/h"})).status_code == 403
    captured = {}

    async def fake_fetch(url, **kw):  # noqa: ANN001, ANN003, ANN202
        captured.update(url=url, **kw)
        from app.fetch.client import FetchResult

        return FetchResult(url, url, 200, {}, b"ok", "text/plain", None, 5)

    from app.notify import channels

    monkeypatch.setattr(channels, "safe_fetch", fake_fetch)
    async with session_scope() as s:
        await s.execute(update(Profile).where(Profile.id == u.id).values(default_channels=["webhook"]))
    aid = await make_alert(u, site)
    await dispatch.fanout_alert({}, str(aid))
    await drain(("notify",))
    body = captured["content"]
    sig = captured["extra_headers"]["X-Watchtower-Signature"]
    ts = int(sig.split(",")[0][2:])
    assert sig == webhook_signature(secret, ts, body)
    assert json.loads(body)["alert_id"] == str(aid)


def svix_headers(secret: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    ts = ts or int(time.time())
    key = base64.b64decode(secret.split("whsec_", 1)[1])
    msg_id = f"msg_{uuid.uuid4().hex}"
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": str(ts), "svix-signature": f"v1,{sig}",
            "webhook-id": msg_id, "webhook-timestamp": str(ts), "webhook-signature": f"v1,{sig}"}


async def test_resend_bounce_suppresses_email(client, make_user, site) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    secret = get_settings().resend_webhook_secret.get_secret_value()
    u = await make_user(email="gone@example.com")
    body = json.dumps({"type": "email.bounced", "data": {"to": ["gone@example.com"], "bounce": {"type": "Permanent"}}}).encode()
    bad = await client.post("/v1/webhooks/resend", content=body, headers={**svix_headers(secret, body), "svix-signature": "v1,AAAA"})
    assert bad.status_code == 401
    old = await client.post("/v1/webhooks/resend", content=body, headers=svix_headers(secret, body, int(time.time()) - 3600))
    assert old.status_code == 401  # replay window
    assert (await client.post("/v1/webhooks/resend", content=body, headers=svix_headers(secret, body))).status_code == 200
    async with session_scope() as s:
        assert await s.get(EmailSuppression, "gone@example.com") is not None
    aid = await make_alert(u, site)
    await dispatch.fanout_alert({}, str(aid))
    assert await deliveries(u.id) == []  # no channel left: nothing sent to a dead address


async def test_auth_hook_blocks_disposable_and_floods(client) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    secret = get_settings().auth_hook_secret.get_secret_value().split(",", 1)[1]
    body = json.dumps({"user": {"email": "x@yopmail.com"}, "metadata": {"ip_address": "1.2.3.4"}}).encode()
    r = await client.post("/v1/hooks/auth/before-user-created", content=body, headers=svix_headers(secret, body))
    assert r.json()["error"]["http_code"] == 400
    for i in range(6):
        b = json.dumps({"user": {"email": f"u{i}@gmail.com"}, "metadata": {"ip_address": "5.6.7.8"}}).encode()
        r = await client.post("/v1/hooks/auth/before-user-created", content=b, headers=svix_headers(secret, b))
    assert r.json()["error"]["http_code"] == 429
    assert (await client.post("/v1/hooks/auth/before-user-created", content=b, headers={})).status_code == 401


async def test_unsubscribe_links_require_post(client, make_user, site) -> None:  # noqa: ANN001
    from app.notify.render import unsubscribe_url

    u = await make_user()
    url = unsubscribe_url(u.id, None).replace("http://localhost:8000", "")
    page = await client.get(url)
    assert page.status_code == 200 and "<form method=\"post\"" in page.text
    async with session_scope() as s:
        assert (await s.get(Profile, u.id)).email_alerts_enabled is True  # GET (mail scanner prefetch) changes nothing
    assert (await client.post(url)).status_code == 200
    async with session_scope() as s:
        assert (await s.get(Profile, u.id)).email_alerts_enabled is False
    forged = url[:-6] + "AAAAAA"
    assert "expired" in (await client.post(forged)).text.lower()


async def test_failed_sends_retry_then_give_up(make_user, site, monkeypatch) -> None:  # noqa: ANN001
    from app.notify import channels
    from app.notify.channels import TransientFailure

    attempts = []

    async def flaky(**kw):  # noqa: ANN003, ANN202
        attempts.append(1)
        raise TransientFailure("smtp down")

    monkeypatch.setattr(channels.email_sender, "send", flaky)
    u = await make_user()
    aid = await make_alert(u, site)
    await dispatch.fanout_alert({}, str(aid))
    await drain(("notify",))
    d = (await deliveries(u.id))[0]
    assert d.status == "failed" and d.attempts == dispatch.MAX_ATTEMPTS and len(attempts) == dispatch.MAX_ATTEMPTS
    _ = get_redis
