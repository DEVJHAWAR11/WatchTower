"""Dodo Payments: hosted checkout, plan changes, customer portal, cancellation and subscription webhooks.

Entitlements live on the profile (`plan_id` + `plan_expires_at`). A webhook moves `plan_expires_at` to the next
billing date plus a short grace period, so a failed renewal downgrades the account on its own once that passes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, ServiceUnavailable, ValidationFailed
from app.core.logging import get_logger
from app.models import AuditLog, Profile

log = get_logger(__name__)

PAID_PLANS = ("plus", "pro")
INTERVALS = ("month", "year")
# Event -> subscription status, used when the payload carries none.
EVENT_STATUS = {
    "subscription.active": "active", "subscription.renewed": "active", "subscription.plan_changed": "active",
    "subscription.updated": None, "subscription.on_hold": "on_hold", "subscription.failed": "failed",
    "subscription.past_due": "past_due", "subscription.cancelled": "cancelled", "subscription.expired": "expired",
}
ACTIVE_STATUSES = {"active", "past_due"}


class BillingError(AppError):
    status_code = 502
    code = "billing_error"


def _require_enabled() -> None:
    if not get_settings().billing_enabled:
        raise ServiceUnavailable("Payments aren't switched on yet.", code="billing_disabled")


def product_id_for(plan_id: str, interval: str, currency: str = "usd") -> str:
    if plan_id not in PAID_PLANS or interval not in INTERVALS:
        raise ValidationFailed("Unknown plan or billing period")
    products = get_settings().dodo_products
    key = f"{plan_id}_{interval}"
    pid = (products.get(f"{key}_inr") if currency == "inr" else None) or products.get(key)
    if not pid:
        raise ServiceUnavailable("This plan isn't available for purchase yet.", code="billing_disabled")
    return pid


def plan_for_product(product_id: str | None) -> tuple[str, str] | None:
    """Reverse lookup: Dodo product id -> (plan_id, interval)."""
    if not product_id:
        return None
    for key, pid in get_settings().dodo_products.items():
        if pid == product_id:
            parts = key.split("_")
            if len(parts) >= 2 and parts[0] in PAID_PLANS and parts[1] in INTERVALS:
                return parts[0], parts[1]
    return None


async def _dodo(method: str, path: str, *, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None,
                http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    s = get_settings()
    own = http is None
    client = http or httpx.AsyncClient(base_url=s.dodo_base_url, timeout=httpx.Timeout(20.0, connect=10.0))
    try:
        r = await client.request(method, path, json=json, params=params,
                                 headers={"Authorization": f"Bearer {s.dodo_api_key.get_secret_value()}"})
    except httpx.HTTPError as e:
        log.warning("dodo_unreachable", path=path, error=str(e))
        raise BillingError("The payment provider couldn't be reached. Try again in a moment.") from e
    finally:
        if own:
            await client.aclose()
    if r.status_code >= 400:
        log.warning("dodo_error", path=path, status=r.status_code, body=r.text[:300])
        raise BillingError("The payment provider rejected the request.", details={"status": r.status_code})
    return r.json() if r.content else {}


def _has_live_subscription(p: Profile) -> bool:
    return bool(p.billing_subscription_id and p.billing_status in ACTIVE_STATUSES)


async def start_checkout(p: Profile, plan_id: str, interval: str, currency: str,
                         http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Return {"checkout_url"} for a new subscription, or {"changed": True} when switching an active one."""
    _require_enabled()
    s = get_settings()
    product_id = product_id_for(plan_id, interval, currency)
    if _has_live_subscription(p):
        if p.plan_id == plan_id and p.billing_interval == interval:
            raise Conflict("You're already on that plan")
        if p.billing_cancel_at_period_end:
            # Dodo refuses plan changes on a subscription that's scheduled to end, so pick it back up first.
            await set_cancel_at_period_end(p, False, http=http)
        await _dodo("POST", f"/subscriptions/{p.billing_subscription_id}/change-plan", http=http,
                    json={"product_id": product_id, "quantity": 1, "proration_billing_mode": "prorated_immediately"})
        return {"changed": True}
    if not p.email:
        raise ValidationFailed("Add an email address to your account before subscribing.")
    customer: dict[str, Any] = ({"customer_id": p.billing_customer_id} if p.billing_customer_id
                                else {"email": p.email, "name": p.display_name or p.email.split("@")[0]})
    base = s.frontend_base_url.rstrip("/")
    body = {
        "product_cart": [{"product_id": product_id, "quantity": 1}],
        "customer": customer,
        "return_url": f"{base}/settings?tab=plan&checkout=done",
        "cancel_url": f"{base}/settings?tab=plan",
        "metadata": {"user_id": str(p.id), "plan_id": plan_id, "interval": interval},
    }
    res = await _dodo("POST", "/checkouts", json=body, http=http)
    url = res.get("checkout_url")
    if not url:
        raise BillingError("The payment provider didn't return a checkout link.")
    return {"checkout_url": url}


async def portal_url(p: Profile, http: httpx.AsyncClient | None = None) -> str:
    _require_enabled()
    if not p.billing_customer_id:
        raise Conflict("There's no subscription to manage yet.")
    res = await _dodo("POST", f"/customers/{p.billing_customer_id}/customer-portal/session", http=http,
                      params={"return_url": f"{get_settings().frontend_base_url.rstrip('/')}/settings?tab=plan"})
    if not res.get("link"):
        raise BillingError("The payment provider didn't return a portal link.")
    return str(res["link"])


async def set_cancel_at_period_end(p: Profile, cancel: bool, http: httpx.AsyncClient | None = None) -> None:
    _require_enabled()
    if not _has_live_subscription(p):
        raise Conflict("You don't have an active subscription.")
    await _dodo("PATCH", f"/subscriptions/{p.billing_subscription_id}", json={"cancel_at_next_billing_date": cancel},
                http=http)
    p.billing_cancel_at_period_end = cancel


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


async def _find_profile(session: AsyncSession, data: dict[str, Any]) -> Profile | None:
    meta = data.get("metadata") or {}
    customer = data.get("customer") or {}
    if meta.get("user_id"):
        try:
            p = await session.get(Profile, uuid.UUID(str(meta["user_id"])))
        except ValueError:
            p = None
        if p is not None:
            return p
    for col, val in ((Profile.billing_subscription_id, data.get("subscription_id")),
                     (Profile.billing_customer_id, customer.get("customer_id"))):
        if val:
            p = (await session.execute(select(Profile).where(col == str(val)))).scalars().first()
            if p is not None:
                return p
    return None


async def apply_subscription_event(session: AsyncSession, event_type: str, data: dict[str, Any]) -> str:
    """Apply one Dodo subscription webhook to the owning profile. Safe to repeat: it writes state, not deltas."""
    if event_type not in EVENT_STATUS:
        return "ignored"
    p = await _find_profile(session, data)
    if p is None:
        log.warning("dodo_unmatched_event", kind=event_type, subscription=data.get("subscription_id"))
        return "unmatched"
    status = str(data.get("status") or EVENT_STATUS[event_type] or p.billing_status or "active")
    mapped = plan_for_product(data.get("product_id"))
    now = datetime.now(UTC)
    grace = timedelta(days=get_settings().billing_grace_days)
    customer = data.get("customer") or {}

    if customer.get("customer_id"):
        p.billing_customer_id = str(customer["customer_id"])
    if data.get("subscription_id"):
        p.billing_subscription_id = str(data["subscription_id"])
    p.billing_status = status
    p.billing_cancel_at_period_end = bool(data.get("cancel_at_next_billing_date"))

    if status in ACTIVE_STATUSES and mapped:
        p.plan_id, p.billing_interval = mapped
        nxt = _parse_dt(data.get("next_billing_date"))
        if status == "active" or p.plan_expires_at is None:
            p.plan_expires_at = (nxt + grace) if nxt else now + timedelta(days=35)
    elif status == "expired" or (status == "cancelled" and (p.plan_expires_at is None or p.plan_expires_at <= now)):
        p.plan_id, p.plan_expires_at = "free", None
        p.billing_subscription_id, p.billing_interval, p.billing_cancel_at_period_end = None, None, False
    # on_hold / failed / cancelled-with-time-left: keep the plan until plan_expires_at passes.

    session.add(AuditLog(actor_id=p.id, action=f"billing.{event_type.split('.', 1)[1]}", target_type="subscription",
                         target_id=str(data.get("subscription_id") or "")[:64],
                         meta={"status": status, "plan_id": p.plan_id, "interval": p.billing_interval}))
    return "applied"
