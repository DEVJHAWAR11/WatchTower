"""Render one complete notification per channel from an alert + its follow-up (act) results."""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import get_settings
from app.core.crypto import sign_payload

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html", "j2.html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass
class AlertMessage:
    alert_id: str
    watch_id: str
    watch_title: str
    title: str
    summary: str
    source_url: str
    created_at: datetime
    details: list[tuple[str, str]] = field(default_factory=list)
    deadlines: list[tuple[str, str]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    comparison: str = ""
    checklist: list[str] = field(default_factory=list)
    draft: str = ""
    pending_actions: list[str] = field(default_factory=list)
    act_note: str = ""

    @property
    def app_url(self) -> str:
        return f"{get_settings().frontend_base_url.rstrip('/')}/alerts/{self.alert_id}"

    @property
    def watch_url(self) -> str:
        return f"{get_settings().frontend_base_url.rstrip('/')}/watches/{self.watch_id}"


def unsubscribe_url(user_id: uuid.UUID, watch_id: str | None) -> str:
    token = sign_payload({"u": str(user_id), "w": watch_id or "*"}, "unsub", ttl_seconds=180 * 24 * 3600)
    return f"{get_settings().public_base_url.rstrip('/')}/v1/unsubscribe?token={token}"


def feedback_url(user_id: uuid.UUID, alert_id: str, relevant: bool) -> str:
    token = sign_payload({"u": str(user_id), "a": alert_id, "r": relevant}, "feedback", ttl_seconds=60 * 24 * 3600)
    return f"{get_settings().public_base_url.rstrip('/')}/v1/feedback/quick?token={token}"


def _fmt_date(value: str, tz: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        return dt.strftime("%a, %d %b %Y") + ("" if len(value) <= 10 else dt.strftime(", %I:%M %p"))
    return dt.astimezone(ZoneInfo(tz)).strftime("%a, %d %b %Y, %I:%M %p")


def build_message(alert: Any, watch: Any, actions: list[Any], tz: str = "Asia/Kolkata") -> AlertMessage:
    act = alert.act_result or {}
    details = list((act.get("key_details") or alert.key_facts or {}).items())[:12]
    msg = AlertMessage(
        alert_id=str(alert.id), watch_id=str(watch.id), watch_title=watch.title,
        title=act.get("headline") or alert.title, summary=act.get("what_happened") or alert.summary,
        source_url=alert.source_url, created_at=alert.created_at,
        details=[(str(k), str(v)) for k, v in details],
        deadlines=[(d.get("label", "Deadline"), _fmt_date(d.get("date", ""), tz)) for d in act.get("deadlines", [])][:6],
        links=[(link.get("name", "Link"), link.get("url", "")) for link in act.get("links", []) if link.get("url")][:6],
        comparison=act.get("comparison") or "", checklist=list(act.get("checklist") or [])[:10],
        draft=act.get("draft_message") or "",
        pending_actions=[a.title for a in actions][:6],
    )
    if alert.act_status in ("failed", "timeout"):
        msg.act_note = "We couldn't finish the follow-up details this time; open the alert for the source."
    return msg


def render_email(msg: AlertMessage, user_id: uuid.UUID) -> tuple[str, str, str, dict[str, str]]:
    unsub = unsubscribe_url(user_id, msg.watch_id)
    ctx = {"m": msg, "unsubscribe_url": unsub, "app_name": get_settings().app_name,
           "relevant_url": feedback_url(user_id, msg.alert_id, True),
           "irrelevant_url": feedback_url(user_id, msg.alert_id, False)}
    subject = f"🔔 {msg.title}"[:150]
    html_body = _env.get_template("alert_email.html").render(**ctx)
    text_body = _env.get_template("alert_email.txt").render(**ctx)
    headers = {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return subject, html_body, text_body, headers


def render_push(msg: AlertMessage) -> dict[str, Any]:
    body = msg.summary[:180]
    if msg.deadlines:
        body = f"{body}\n⏰ {msg.deadlines[0][0]}: {msg.deadlines[0][1]}"[:240]
    return {"title": msg.title[:80], "body": body, "url": msg.app_url, "tag": f"alert-{msg.alert_id}",
            "data": {"alert_id": msg.alert_id, "watch_id": msg.watch_id}}


def render_telegram(msg: AlertMessage) -> str:
    e = html.escape
    parts = [f"🔔 <b>{e(msg.title)}</b>", e(msg.summary)]
    if msg.details:
        parts.append("\n".join(f"• <b>{e(k)}:</b> {e(v)}" for k, v in msg.details[:8]))
    if msg.deadlines:
        parts.append("⏰ " + "\n⏰ ".join(f"{e(k)}: <b>{e(v)}</b>" for k, v in msg.deadlines))
    if msg.comparison:
        parts.append(f"↔️ {e(msg.comparison[:500])}")
    if msg.pending_actions:
        parts.append("✅ Waiting for your approval: " + e(", ".join(msg.pending_actions)))
    if msg.act_note:
        parts.append(f"<i>{e(msg.act_note)}</i>")
    parts.append(f'<a href="{e(msg.source_url, quote=True)}">Source</a> · <a href="{e(msg.app_url, quote=True)}">Open in Watchtower</a>')
    parts.append(f"<i>Watch: {e(msg.watch_title)}</i>")
    return "\n\n".join(parts)[:4000]


def render_webhook(msg: AlertMessage) -> dict[str, Any]:
    return {
        "type": "alert", "alert_id": msg.alert_id, "watch_id": msg.watch_id, "watch_title": msg.watch_title,
        "title": msg.title, "summary": msg.summary, "source_url": msg.source_url,
        "details": dict(msg.details), "deadlines": [{"label": k, "when": v} for k, v in msg.deadlines],
        "links": [{"name": k, "url": v} for k, v in msg.links], "pending_actions": msg.pending_actions,
        "created_at": msg.created_at.isoformat(), "app_url": msg.app_url,
    }


def render_digest_email(items: list[AlertMessage], user_id: uuid.UUID, date_label: str) -> tuple[str, str, str, dict[str, str]]:
    unsub = unsubscribe_url(user_id, None)
    ctx = {"items": items, "date_label": date_label, "unsubscribe_url": unsub, "app_name": get_settings().app_name,
           "app_url": get_settings().frontend_base_url}
    subject = f"Your Watchtower digest: {len(items)} update{'s' if len(items) != 1 else ''} ({date_label})"
    headers = {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return (subject, _env.get_template("digest_email.html").render(**ctx),
            _env.get_template("digest_email.txt").render(**ctx), headers)


def render_simple_email(title: str, body: str, link: str | None, user_id: uuid.UUID) -> tuple[str, str, str, dict[str, str]]:
    unsub = unsubscribe_url(user_id, None)
    url = f"{get_settings().frontend_base_url.rstrip('/')}{link}" if link and link.startswith("/") else link
    ctx = {"title": title, "body": body, "link": url, "unsubscribe_url": unsub, "app_name": get_settings().app_name}
    return (title[:150], _env.get_template("simple_email.html").render(**ctx),
            _env.get_template("simple_email.txt").render(**ctx),
            {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
