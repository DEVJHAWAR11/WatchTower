"""Unauthenticated, signed-link endpoints used from emails: one-click unsubscribe and quick feedback.

GET only renders a confirmation page (mail scanners prefetch GET links); the change happens on POST.
RFC 8058 one-click unsubscribe POSTs straight to the same URL.
"""

from __future__ import annotations

import html
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import update

from app.api.deps import DB, rate_limit
from app.core.crypto import verify_payload
from app.models import Alert, Profile, Subscription

router = APIRouter(tags=["public"])


def _page(title: str, body: str, form_action: str | None = None, button: str | None = None) -> HTMLResponse:
    form = (f'<form method="post" action="{html.escape(form_action, quote=True)}"><button type="submit" '
            f'style="padding:10px 16px;border-radius:8px;border:0;background:#2457d6;color:#fff;font-size:15px">'
            f"{html.escape(button or 'Confirm')}</button></form>") if form_action else ""
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
           f"<meta name='robots' content='noindex'><title>{html.escape(title)}</title></head>"
           f"<body style='font-family:system-ui,sans-serif;max-width:520px;margin:60px auto;padding:0 16px'>"
           f"<h2>{html.escape(title)}</h2><p>{html.escape(body)}</p>{form}</body></html>")
    return HTMLResponse(doc, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                                                 "form-action 'self'"})


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page(token: str, request: Request) -> HTMLResponse:
    data = verify_payload(token, "unsub")
    if not data:
        return _page("Link expired", "This unsubscribe link is invalid or has expired. Manage alerts in Settings.")
    what = "all Watchtower email alerts" if data.get("w") == "*" else "emails for this watch"
    return _page("Unsubscribe", f"Stop {what}?", str(request.url), "Unsubscribe")


@router.post("/unsubscribe", response_class=HTMLResponse,
             dependencies=[Depends(rate_limit("unsub", 30, 3600, per="ip"))])
async def unsubscribe(token: str, session: DB) -> HTMLResponse:
    data = verify_payload(token, "unsub")
    if not data:
        return _page("Link expired", "This unsubscribe link is invalid or has expired.")
    uid = uuid.UUID(data["u"])
    if data.get("w") == "*":
        await session.execute(update(Profile).where(Profile.id == uid).values(email_alerts_enabled=False))
        return _page("Unsubscribed", "You won't get email alerts anymore. Push/Telegram settings are unchanged.")
    await session.execute(update(Subscription).where(Subscription.user_id == uid,
                                                     Subscription.watch_id == uuid.UUID(data["w"])).values(muted=True))
    return _page("Unsubscribed", "You won't get notifications for this watch anymore. You can unmute it in the app.")


@router.get("/feedback/quick", response_class=HTMLResponse)
async def quick_feedback_page(token: str, request: Request) -> HTMLResponse:
    data = verify_payload(token, "feedback")
    if not data:
        return _page("Link expired", "This link is invalid or has expired.")
    label = "useful" if data.get("r") else "not relevant"
    return _page("Thanks!", f"Mark this alert as {label}? This teaches the watch what you care about.",
                 str(request.url), "Yes, record it")


@router.post("/feedback/quick", response_class=HTMLResponse,
             dependencies=[Depends(rate_limit("quickfb", 60, 3600, per="ip"))])
async def quick_feedback(token: str, session: DB) -> HTMLResponse:
    data = verify_payload(token, "feedback")
    if not data:
        return _page("Link expired", "This link is invalid or has expired.")
    from app.api.v1.alerts import record_feedback

    user = await session.get(Profile, uuid.UUID(data["u"]))
    alert = await session.get(Alert, uuid.UUID(data["a"]))
    if user is None or alert is None:
        return _page("Not found", "That alert no longer exists.")
    await record_feedback(session, user, alert, bool(data.get("r")), None)
    await session.commit()
    from app.agents.refine import maybe_trigger_refinement

    await maybe_trigger_refinement(alert.watch_id)
    return _page("Recorded", "Thanks! Your watch will use this to get smarter.")
