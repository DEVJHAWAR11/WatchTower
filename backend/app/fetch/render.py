"""Optional headless-browser rendering for JS-heavy pages (install the `render` extra + `playwright install chromium`).

Every request the page makes is intercepted and checked with the same SSRF rules; images/media/fonts are
blocked to save bandwidth. Concurrency is capped per process.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.logging import get_logger
from app.fetch.client import FetchBlockedURL, FetchError, FetchResult, FetchTimeout
from app.fetch.ssrf import SSRFBlocked, resolve_public, validate_url

log = get_logger(__name__)

_browser: Any = None
_pw: Any = None
_lock = asyncio.Lock()
_sem: asyncio.Semaphore | None = None
_BLOCKED_RESOURCES = {"image", "media", "font", "websocket", "eventsource", "manifest"}


def render_available() -> bool:
    if not get_settings().render_enabled:
        return False
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


async def _get_browser() -> Any:
    global _browser, _pw, _sem
    async with _lock:
        if _browser is None:
            from playwright.async_api import async_playwright

            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-first-run", "--disable-extensions", "--disable-sync",
                      "--disable-background-networking", "--js-flags=--max-old-space-size=256"],
            )
            _sem = asyncio.Semaphore(get_settings().render_max_concurrency)
    return _browser


async def close_renderer() -> None:
    global _browser, _pw
    if _browser is not None:
        await _browser.close()
    if _pw is not None:
        await _pw.stop()
    _browser = _pw = None


async def render_page(url: str, timeout_s: float = 25.0) -> FetchResult:
    if not render_available():
        raise FetchError("JS rendering is not enabled on this deployment", code="render_unavailable")
    try:
        validate_url(url)
    except SSRFBlocked as e:
        raise FetchBlockedURL(f"URL not allowed: {e.reason}") from e
    browser = await _get_browser()
    assert _sem is not None
    async with _sem:
        started = time.monotonic()
        context = await browser.new_context(
            user_agent=get_settings().fetch_user_agent, java_script_enabled=True, accept_downloads=False,
            service_workers="block", locale="en-IN", timezone_id="Asia/Kolkata",
        )
        page = await context.new_page()

        async def guard(route: Any) -> None:
            req = route.request
            if req.resource_type in _BLOCKED_RESOURCES:
                await route.abort()
                return
            try:
                validate_url(req.url)
                parts = urlsplit(req.url)
                await resolve_public(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
            except SSRFBlocked:
                log.warning("render_request_blocked", url=req.url[:200])
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await page.route("**/*", guard)
        try:
            resp = await page.goto(url, wait_until="networkidle", timeout=timeout_s * 1000)
            html = await page.content()
            status = resp.status if resp else 200
            headers = {k.lower(): v for k, v in (await resp.all_headers()).items()} if resp else {}
            final_url = page.url
        except Exception as e:  # playwright raises its own TimeoutError type
            if "Timeout" in type(e).__name__:
                raise FetchTimeout("Render timed out") from e
            raise FetchError(f"Render failed: {type(e).__name__}") from e
        finally:
            await context.close()
    body = html.encode("utf-8")[: get_settings().fetch_max_bytes]
    return FetchResult(
        url=url, final_url=final_url, status_code=status, headers=headers, content=body,
        content_type="text/html", encoding="utf-8", elapsed_ms=int((time.monotonic() - started) * 1000),
    )
