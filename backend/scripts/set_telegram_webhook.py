"""Register the Telegram webhook: python scripts/set_telegram_webhook.py https://api.yourdomain.com"""

import sys

import httpx

from app.core.config import get_settings

s = get_settings()
base = sys.argv[1].rstrip("/")
r = httpx.post(f"{s.telegram_api_base}/bot{s.telegram_bot_token.get_secret_value()}/setWebhook", json={
    "url": f"{base}/v1/webhooks/telegram", "secret_token": s.telegram_webhook_secret.get_secret_value(),
    "allowed_updates": ["message", "callback_query"], "drop_pending_updates": True,
})
print(r.status_code, r.text)
