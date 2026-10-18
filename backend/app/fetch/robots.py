"""robots.txt compliance (RFC 9309) with Redis caching, plus per-domain politeness (shared token bucket)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.core.config import get_settings
from app.core.redis import cache_get_json, cache_set_json, token_bucket_take
from app.fetch.client import FetchError, safe_fetch

ROBOTS_TTL_OK = 24 * 3600
ROBOTS_TTL_ERROR = 3600
ROBOTS_UA_TOKEN = "WatchtowerBot"  # noqa: S105 - robots.txt user-agent token


@dataclass
class RobotsDecision:
    allowed: bool
    crawl_delay: float | None
    reason: str


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


async def _load_robots(origin: str) -> dict[str, object]:
    key = f"robots:{origin}"
    cached = await cache_get_json(key)
    if cached is not None:
        return cached
    entry: dict[str, object]
    try:
        res = await safe_fetch(f"{origin}/robots.txt", max_bytes=512 * 1024, allow_any_content_type=True)
        if res.status_code >= 500:
            # RFC 9309 §2.3.1.4: unreachable -> assume complete disallow (temporarily).
            entry = {"mode": "disallow_all", "body": ""}
            ttl = ROBOTS_TTL_ERROR
        elif res.status_code >= 400:
            entry = {"mode": "allow_all", "body": ""}
            ttl = ROBOTS_TTL_OK
        else:
            entry = {"mode": "rules", "body": res.content.decode("utf-8", "replace")[:500_000]}
            ttl = ROBOTS_TTL_OK
    except FetchError as e:
        if e.code == "url_blocked":
            raise
        entry = {"mode": "allow_all", "body": ""}
        ttl = ROBOTS_TTL_ERROR
    await cache_set_json(key, entry, ttl)
    return entry


async def check_robots(url: str) -> RobotsDecision:
    if not get_settings().fetch_respect_robots:
        return RobotsDecision(True, None, "robots checks disabled")
    origin = _origin(url)
    entry = await _load_robots(origin)
    mode = entry.get("mode")
    if mode == "allow_all":
        return RobotsDecision(True, None, "no robots.txt")
    if mode == "disallow_all":
        return RobotsDecision(False, None, "robots.txt unreachable (server error); retrying later")
    parser = RobotFileParser()
    parser.parse(str(entry.get("body", "")).splitlines())
    allowed = parser.can_fetch(ROBOTS_UA_TOKEN, url)
    delay = parser.crawl_delay(ROBOTS_UA_TOKEN)
    return RobotsDecision(
        allowed,
        float(delay) if delay is not None else None,
        "allowed by robots.txt" if allowed else "disallowed by the site's robots.txt",
    )


class DomainBusy(Exception):
    def __init__(self, wait_seconds: float):
        super().__init__(f"domain busy, retry in {wait_seconds:.1f}s")
        self.wait_seconds = wait_seconds


async def acquire_domain_slot(domain: str, min_interval: float | None = None, max_wait: float = 8.0) -> None:
    """Global (cross-worker) politeness: at most one request per `min_interval` seconds per domain."""
    interval = max(min_interval or 0.0, get_settings().fetch_default_domain_interval_seconds, 0.2)
    rate = 1.0 / interval
    waited = 0.0
    while True:
        ok, wait_ms = await token_bucket_take(f"dom:{domain}", rate, 2.0)
        if ok:
            return
        wait = wait_ms / 1000.0
        if waited + wait > max_wait:
            raise DomainBusy(wait)
        await asyncio.sleep(wait)
        waited += wait
