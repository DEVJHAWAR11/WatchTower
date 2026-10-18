"""Classify a fetch result: ok / blocked (bot wall, rate-limited) / gone / server error / client error."""

from __future__ import annotations

from dataclasses import dataclass

_CHALLENGE_MARKERS = (
    "cf-browser-verification", "challenge-platform", "cf-chl-", "attention required! | cloudflare",
    "just a moment...", "checking your browser", "ddos protection by", "request unsuccessful. incapsula",
    "_incapsula_resource", "px-captcha", "perimeterx", "datadome", "captcha-delivery.com", "g-recaptcha",
    "h-captcha", "hcaptcha.com", "are you a robot", "unusual traffic from your computer", "verify you are human",
    "access denied</title>", "reference #18.", "bot detection", "please enable js and disable any ad blocker",
    "the requested url was rejected. please consult with your administrator",
)


@dataclass
class Classification:
    kind: str  # ok | not_modified | blocked | gone | server_error | client_error
    reason: str
    retry_after: int | None = None


def classify_response(status: int, headers: dict[str, str], body_head: str, text_len: int) -> Classification:
    low = body_head[:20000].lower()
    retry_after = None
    ra = headers.get("retry-after", "")
    if ra.isdigit():
        retry_after = min(int(ra), 24 * 3600)
    if status == 304:
        return Classification("not_modified", "Not modified (conditional GET)")
    if status in (404, 410):
        return Classification("gone", f"Page returned HTTP {status}")
    if status == 429:
        return Classification("blocked", "Rate limited by site (HTTP 429)", retry_after or 3600)
    challenge = any(m in low for m in _CHALLENGE_MARKERS)
    if status in (401, 403, 451) or (status == 503 and challenge):
        why = "bot protection challenge" if challenge else f"access denied (HTTP {status})"
        return Classification("blocked", f"Site blocked automated access: {why}", retry_after)
    if status >= 500:
        return Classification("server_error", f"Site error (HTTP {status})", retry_after)
    if status >= 400:
        return Classification("client_error", f"Request rejected (HTTP {status})")
    if challenge and text_len < 3000:
        return Classification("blocked", "Site served a bot-check page instead of content", retry_after)
    return Classification("ok", "OK")
