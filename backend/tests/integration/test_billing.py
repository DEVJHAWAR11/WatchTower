import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy import update

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import Check, Profile, UsageCounter
from app.services.plans import period_start
from app.workers.checks import run_check
from tests.helpers import get_check, make_watch


def signed(body: dict, ts: int | None = None, secret: str | None = None) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    ts = ts or int(time.time())
    secret = secret or get_settings().dodo_webhook_secret.get_secret_value()
    key = base64.b64decode(secret.split("whsec_", 1)[1])
    msg_id = f"evt_{uuid.uuid4().hex}"
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256).digest()).decode()
    return raw, {"webhook-id": msg_id, "webhook-timestamp": str(ts), "webhook-signature": f"v1,{sig}"}


def sub_event(kind: str, user: Profile, *, product: str = "pdt_plus_month", status: str | None = None,
              nxt: datetime | None = None, cancel: bool = False) -> dict:
    nxt = nxt or datetime.now(UTC) + timedelta(days=30)
    data = {"subscription_id": "sub_123", "product_id": product, "customer": {"customer_id": "cus_9", "email": user.email},
            "metadata": {"user_id": str(user.id)}, "next_billing_date": nxt.isoformat(),
            "cancel_at_next_billing_date": cancel}
    if status:
        data["status"] = status
    return {"type": f"subscription.{kind}", "timestamp": datetime.now(UTC).isoformat(), "data": data}


async def post_event(client, body: dict):  # noqa: ANN001, ANN201
    raw, headers = signed(body)
    return await client.post("/v1/webhooks/dodo", content=raw, headers=headers)


async def profile(uid: uuid.UUID) -> Profile:
    async with session_scope() as s:
        p = await s.get(Profile, uid)
        s.expunge(p)
        return p


async def test_webhook_rejects_bad_and_stale_signatures(client, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    raw, headers = signed(sub_event("active", u))
    assert (await client.post("/v1/webhooks/dodo", content=raw, headers={**headers, "webhook-signature": "v1,AAAA"})).status_code == 401
    old_raw, old = signed(sub_event("active", u), ts=int(time.time()) - 3600)
    assert (await client.post("/v1/webhooks/dodo", content=old_raw, headers=old)).status_code == 401
    assert (await client.post("/v1/webhooks/dodo", content=raw)).status_code == 401
    assert (await profile(u.id)).plan_id == "free"


async def test_subscription_lifecycle_moves_the_plan(client, auth, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    nxt = datetime.now(UTC) + timedelta(days=30)
    r = await post_event(client, sub_event("active", u, nxt=nxt))
    assert r.status_code == 200 and r.json()["result"] == "applied"
    b = (await client.get("/v1/billing", headers=h)).json()
    assert b["plan_id"] == "plus" and b["interval"] == "month" and b["status"] == "active" and b["has_subscription"]
    assert (await client.get("/v1/me/usage", headers=h)).json()["plan"]["id"] == "plus"
    p = await profile(u.id)
    assert p.billing_customer_id == "cus_9" and p.plan_expires_at > nxt  # grace days on top of the renewal date

    # upgrade to Pro (yearly)
    await post_event(client, sub_event("plan_changed", u, product="pdt_pro_year", nxt=nxt + timedelta(days=335)))
    b = (await client.get("/v1/billing", headers=h)).json()
    assert b["plan_id"] == "pro" and b["interval"] == "year"

    # failed renewal: keep the plan until the paid period (plus grace) runs out
    await post_event(client, sub_event("on_hold", u, product="pdt_pro_year", status="on_hold"))
    assert (await client.get("/v1/billing", headers=h)).json()["plan_id"] == "pro"

    # user schedules a cancellation, then the term ends
    await post_event(client, sub_event("updated", u, product="pdt_pro_year", status="active", cancel=True))
    assert (await client.get("/v1/billing", headers=h)).json()["cancel_at_period_end"] is True
    await post_event(client, sub_event("expired", u, product="pdt_pro_year", status="expired"))
    b = (await client.get("/v1/billing", headers=h)).json()
    assert b["plan_id"] == "free" and b["has_subscription"] is True  # customer id is kept for the portal
    p = await profile(u.id)
    assert p.billing_subscription_id is None and p.plan_expires_at is None


async def test_cancelled_keeps_access_until_the_paid_period_ends(client, auth, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    await post_event(client, sub_event("active", u))
    await post_event(client, sub_event("cancelled", u, status="cancelled"))
    assert (await client.get("/v1/billing", headers=h)).json()["plan_id"] == "plus"
    async with session_scope() as s:
        await s.execute(update(Profile).where(Profile.id == u.id).values(plan_expires_at=datetime.now(UTC) - timedelta(days=1)))
    assert (await client.get("/v1/billing", headers=h)).json()["plan_id"] == "free"  # lapsed -> free limits again


async def test_unmatched_and_unknown_events_are_acknowledged(client, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    ghost = sub_event("active", u)
    ghost["data"]["metadata"] = {"user_id": str(uuid.uuid4())}
    ghost["data"].update(subscription_id="sub_none", customer={"customer_id": "cus_none"})
    r = await post_event(client, ghost)
    assert r.status_code == 200 and r.json()["result"] == "unmatched"
    r = await post_event(client, {"type": "payment.succeeded", "data": {"payload_type": "Payment"}})
    assert r.status_code == 200 and r.json()["result"] == "ignored"
    assert (await profile(u.id)).plan_id == "free"


@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_checkout_portal_cancel_and_plan_change(client, auth, make_user, respx_mock) -> None:  # noqa: ANN001
    s = get_settings()
    u = await make_user()
    h = auth(u)
    assert (await client.get("/v1/billing", headers=h)).json()["enabled"] is True
    assert (await client.post("/v1/billing/checkout", headers=h, json={"plan_id": "gold"})).status_code == 422

    route = respx_mock.post("https://test.dodopayments.com/checkouts").mock(
        return_value=httpx.Response(200, json={"session_id": "cks_1", "checkout_url": "https://checkout.example/pay/cks_1"}))
    r = await client.post("/v1/billing/checkout", headers=h, json={"plan_id": "plus", "interval": "year"})
    assert r.status_code == 200 and r.json()["checkout_url"] == "https://checkout.example/pay/cks_1"
    sent = json.loads(route.calls.last.request.content)
    assert sent["product_cart"] == [{"product_id": "pdt_plus_year", "quantity": 1}]
    assert sent["metadata"] == {"user_id": str(u.id), "plan_id": "plus", "interval": "year"}
    assert sent["customer"]["email"] == u.email and sent["return_url"].startswith(s.frontend_base_url)
    assert route.calls.last.request.headers["authorization"] == f"Bearer {s.dodo_api_key.get_secret_value()}"

    # rupee product is preferred for INR when configured, falls back to the USD one otherwise
    await client.post("/v1/billing/checkout", headers=h, json={"plan_id": "pro", "interval": "month", "currency": "inr"})
    assert json.loads(route.calls.last.request.content)["product_cart"][0]["product_id"] == "pdt_pro_month_inr"
    await client.post("/v1/billing/checkout", headers=h, json={"plan_id": "plus", "interval": "month", "currency": "inr"})
    assert json.loads(route.calls.last.request.content)["product_cart"][0]["product_id"] == "pdt_plus_month"

    # nothing to cancel or manage before subscribing
    assert (await client.post("/v1/billing/cancel", headers=h)).status_code == 409
    assert (await client.post("/v1/billing/portal", headers=h)).status_code == 409

    await post_event(client, sub_event("active", u))
    assert (await client.post("/v1/billing/checkout", headers=h, json={"plan_id": "plus", "interval": "month"})).status_code == 409

    change = respx_mock.post("https://test.dodopayments.com/subscriptions/sub_123/change-plan").mock(
        return_value=httpx.Response(200, json={}))
    r = await client.post("/v1/billing/checkout", headers=h, json={"plan_id": "pro", "interval": "month"})
    assert r.status_code == 200 and r.json() == {"changed": True}
    assert json.loads(change.calls.last.request.content) == {
        "product_id": "pdt_pro_month", "quantity": 1, "proration_billing_mode": "prorated_immediately"}

    patch = respx_mock.patch("https://test.dodopayments.com/subscriptions/sub_123").mock(return_value=httpx.Response(200, json={}))
    assert (await client.post("/v1/billing/cancel", headers=h)).json() == {"cancel_at_period_end": True}
    assert json.loads(patch.calls.last.request.content) == {"cancel_at_next_billing_date": True}
    assert (await client.get("/v1/billing", headers=h)).json()["cancel_at_period_end"] is True
    assert (await client.post("/v1/billing/resume", headers=h)).json() == {"cancel_at_period_end": False}

    respx_mock.post("https://test.dodopayments.com/customers/cus_9/customer-portal/session").mock(
        return_value=httpx.Response(200, json={"link": "https://portal.example/s/1"}))
    assert (await client.post("/v1/billing/portal", headers=h)).json() == {"url": "https://portal.example/s/1"}

    respx_mock.post("https://test.dodopayments.com/checkouts").mock(return_value=httpx.Response(500, text="boom"))
    other = await make_user()
    r = await client.post("/v1/billing/checkout", headers=auth(other), json={"plan_id": "plus"})
    assert r.status_code == 502 and "boom" not in r.text


async def test_checks_over_the_monthly_allowance_are_deferred(make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    url = site.set("site.test", "/cap", "<p>x</p>")
    wid = await make_watch(u, {"sources": [{"url": url}], "condition": "anything"})
    chk = await get_check(wid)
    async with session_scope() as s:
        await s.execute(update(Check).where(Check.id == chk.id).values(lease_token="tok"))
        s.add(UsageCounter(user_id=u.id, metric="checks", period="month", period_start=period_start("month"), value=1000))
    assert await run_check({}, str(chk.id), "tok") == {"skipped": "checks_cap"}
    after = await get_check(wid)
    assert after.next_run_at > datetime.now(UTC) + timedelta(days=0) and after.lease_token is None
    nxt = after.next_run_at
    assert nxt.day == 1 or nxt > datetime.now(UTC) + timedelta(hours=1)
