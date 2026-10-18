"""Delivery channels. Each sender raises PermanentFailure (don't retry; maybe disable the channel) or
TransientFailure (retry with backoff)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import smtplib
import time
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.fetch.client import FetchError, safe_fetch

log = get_logger(__name__)

# Web Push endpoints must belong to a real push service (the endpoint is user-supplied -> SSRF otherwise).
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com",
    "notify.windows.com", "push.apple.com", "web.push.apple.com",
)


class DeliveryFailure(Exception):
    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentFailure(DeliveryFailure):
    pass


class TransientFailure(DeliveryFailure):
    pass


def push_endpoint_allowed(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == s or host.endswith("." + s) for s in PUSH_HOST_SUFFIXES)


# ------------------------------------------------------------------ email
class EmailSender:
    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str, headers: dict[str, str],
                   idempotency_key: str, tags: dict[str, str] | None = None) -> str:
        s = get_settings()
        if s.email_provider == "resend":
            return await self._resend(to, subject, html_body, text_body, headers, idempotency_key, tags or {})
        if s.email_provider == "smtp":
            return await asyncio.to_thread(self._smtp, to, subject, html_body, text_body, headers)
        # console provider: development + tests. Kept in Redis so tests/dev tools can inspect it.
        record = {"to": to, "subject": subject, "text": text_body, "html": html_body, "headers": headers,
                  "key": idempotency_key}
        await get_redis().lpush("outbox:email", json.dumps(record))
        await get_redis().ltrim("outbox:email", 0, 499)
        log.info("email_console", to=to, subject=subject)
        return f"console-{idempotency_key}"

    async def _resend(self, to: str, subject: str, html_body: str, text_body: str, headers: dict[str, str],
                      key: str, tags: dict[str, str]) -> str:
        s = get_settings()
        body = {"from": s.email_from, "to": [to], "subject": subject, "html": html_body, "text": text_body,
                "headers": headers, "tags": [{"name": k, "value": v} for k, v in tags.items()]}
        req_headers = {"Authorization": f"Bearer {s.resend_api_key.get_secret_value()}", "Idempotency-Key": key}
        client = self._http or httpx.AsyncClient(timeout=15.0, trust_env=False)
        try:
            resp = await client.post("https://api.resend.com/emails", json=body, headers=req_headers)
        except httpx.HTTPError as e:
            raise TransientFailure(f"resend unreachable: {type(e).__name__}") from e
        finally:
            if self._http is None:
                await client.aclose()
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientFailure(f"resend {resp.status_code}", retry_after=int(resp.headers.get("retry-after", "30") or 30))
        if resp.status_code >= 400:
            raise PermanentFailure(f"resend rejected: {resp.status_code} {resp.text[:200]}")
        return str(resp.json().get("id", ""))

    def _smtp(self, to: str, subject: str, html_body: str, text_body: str, headers: dict[str, str]) -> str:
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = to
        msg["Subject"] = subject
        for k, v in headers.items():
            msg[k] = v
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                if s.smtp_starttls:
                    smtp.starttls()
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
                smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
            raise PermanentFailure("recipient refused") from e
        except (smtplib.SMTPException, OSError) as e:
            raise TransientFailure(f"smtp error: {type(e).__name__}") from e
        return f"smtp-{int(time.time() * 1000)}"


# ------------------------------------------------------------------ web push
class WebPushSender:
    def available(self) -> bool:
        s = get_settings()
        return bool(s.vapid_private_key.get_secret_value() and s.vapid_public_key)

    async def send(self, *, endpoint: str, p256dh: str, auth: str, payload: dict[str, Any]) -> str:
        if not push_endpoint_allowed(endpoint):
            raise PermanentFailure("push endpoint not allowed")
        if not self.available():
            raise PermanentFailure("web push not configured")
        from pywebpush import WebPushException, webpush

        s = get_settings()

        def _send() -> int:
            resp = webpush(
                subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
                data=json.dumps(payload), vapid_private_key=s.vapid_private_key.get_secret_value(),
                vapid_claims={"sub": s.vapid_subject}, ttl=24 * 3600, timeout=10,
            )
            return int(getattr(resp, "status_code", 201))

        try:
            status = await asyncio.to_thread(_send)
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                raise PermanentFailure("push subscription expired") from e
            if code == 429 or (code and code >= 500):
                raise TransientFailure(f"push service {code}") from e
            raise PermanentFailure(f"push rejected {code}") from e
        except Exception as e:
            raise TransientFailure(f"push error: {type(e).__name__}") from e
        return f"push-{status}"


# ------------------------------------------------------------------ telegram
class TelegramSender:
    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http

    def available(self) -> bool:
        return bool(get_settings().telegram_bot_token.get_secret_value())

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        s = get_settings()
        url = f"{s.telegram_api_base}/bot{s.telegram_bot_token.get_secret_value()}/{method}"
        client = self._http or httpx.AsyncClient(timeout=15.0, trust_env=False)
        try:
            resp = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            raise TransientFailure(f"telegram unreachable: {type(e).__name__}") from e
        finally:
            if self._http is None:
                await client.aclose()
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code == 429:
            ra = int((data.get("parameters") or {}).get("retry_after", 30))
            raise TransientFailure("telegram rate limited", retry_after=ra)
        if resp.status_code in (400, 403):
            raise PermanentFailure(f"telegram {resp.status_code}: {str(data.get('description', ''))[:200]}")
        if resp.status_code >= 500 or not data.get("ok"):
            raise TransientFailure(f"telegram error {resp.status_code}")
        return data.get("result") or {}

    async def send(self, *, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> str:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        res = await self.call("sendMessage", payload)
        return str(res.get("message_id", ""))


# ------------------------------------------------------------------ outgoing webhooks
def webhook_signature(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


class WebhookSender:
    async def send(self, *, url: str, secret: str, payload: dict[str, Any], delivery_id: str) -> str:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        ts = int(time.time())
        headers = {"Content-Type": "application/json", "X-Watchtower-Signature": webhook_signature(secret, ts, body),
                   "X-Watchtower-Delivery": delivery_id}
        try:
            # SSRF-safe client: user-supplied URL
            res = await safe_fetch(url, method="POST", content=body, extra_headers=headers,
                                   allow_any_content_type=True, max_bytes=64 * 1024)
        except FetchError as e:
            if e.code == "url_blocked":
                raise PermanentFailure("webhook URL not allowed") from e
            raise TransientFailure(f"webhook unreachable: {e.code}") from e
        if 200 <= res.status_code < 300:
            return f"webhook-{res.status_code}"
        if res.status_code in (410,):
            raise PermanentFailure("webhook endpoint gone")
        raise TransientFailure(f"webhook returned {res.status_code}")


email_sender = EmailSender()
push_sender = WebPushSender()
telegram_sender = TelegramSender()
webhook_sender = WebhookSender()
