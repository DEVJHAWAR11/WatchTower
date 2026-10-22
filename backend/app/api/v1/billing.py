"""Subscriptions: status, hosted checkout (Dodo Payments), customer portal and cancel/resume."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import DB, CurrentUser, rate_limit
from app.core.config import get_settings
from app.models import AuditLog
from app.schemas.api import BillingOut, CheckoutIn
from app.services import billing
from app.services.plans import effective_plan_id

router = APIRouter(tags=["billing"])


@router.get("/billing", response_model=BillingOut)
async def billing_status(user: CurrentUser) -> BillingOut:
    s = get_settings()
    return BillingOut(
        enabled=s.billing_enabled, mode=s.dodo_mode, plan_id=effective_plan_id(user), interval=user.billing_interval,
        status=user.billing_status, renews_at=user.plan_expires_at if user.billing_subscription_id else None,
        cancel_at_period_end=user.billing_cancel_at_period_end, has_subscription=bool(user.billing_customer_id),
    )


@router.post("/billing/checkout", dependencies=[Depends(rate_limit("checkout", 10, 3600))])
async def checkout(body: CheckoutIn, user: CurrentUser, session: DB) -> dict[str, Any]:
    res = await billing.start_checkout(user, body.plan_id, body.interval, body.currency)
    session.add(AuditLog(actor_id=user.id, action="billing.checkout", target_type="plan", target_id=body.plan_id,
                         meta={"interval": body.interval, "currency": body.currency, "changed": bool(res.get("changed"))}))
    return res


@router.post("/billing/portal", dependencies=[Depends(rate_limit("billing_portal", 10, 3600))])
async def portal(user: CurrentUser) -> dict[str, str]:
    return {"url": await billing.portal_url(user)}


@router.post("/billing/cancel", dependencies=[Depends(rate_limit("billing_cancel", 10, 3600))])
async def cancel(user: CurrentUser, session: DB) -> dict[str, bool]:
    await billing.set_cancel_at_period_end(user, True)
    session.add(AuditLog(actor_id=user.id, action="billing.cancel_requested", target_type="user", target_id=str(user.id)))
    return {"cancel_at_period_end": True}


@router.post("/billing/resume", dependencies=[Depends(rate_limit("billing_cancel", 10, 3600))])
async def resume(user: CurrentUser, session: DB) -> dict[str, bool]:
    await billing.set_cancel_at_period_end(user, False)
    session.add(AuditLog(actor_id=user.id, action="billing.resume", target_type="user", target_id=str(user.id)))
    return {"cancel_at_period_end": False}
