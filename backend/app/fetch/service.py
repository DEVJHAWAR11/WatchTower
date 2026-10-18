"""Shared-source fetching: one fetch per URL serves every watch that points at it.

Guarantees:
  * freshness reuse  - a snapshot younger than `max_age` is reused (no network)
  * single-flight    - concurrent requests for the same URL wait on one fetch (Redis lock)
  * politeness       - robots.txt + per-domain token bucket shared by all workers
  * conditional GET  - ETag / Last-Modified; unchanged bodies don't create new snapshots
  * failure memory   - blocked/gone/error states are recorded on the source and domain
"""

from __future__ import annotations

import asyncio
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import RedisLock
from app.fetch.classify import classify_response
from app.fetch.client import FetchError, FetchResult, safe_fetch
from app.fetch.extract import decode_body, extract, extract_html
from app.fetch.normalize import content_hash, simhash64
from app.fetch.render import render_available, render_page
from app.fetch.robots import DomainBusy, acquire_domain_slot, check_robots
from app.fetch.urls import canonicalize_url, domain_of
from app.models import DomainPolicy, Source, SourceSnapshot
from app.observability.metrics import FETCH_DURATION, FETCH_TOTAL

log = get_logger(__name__)

MAX_RAW_STORE = 2 * 1024 * 1024
GONE_THRESHOLD = 3


class SourceUnavailable(Exception):
    """kind: blocked | gone | server_error | client_error | robots | timeout | url_blocked | busy | render_unavailable
    | connect_error | too_large | bad_content_type | fetch_error"""

    def __init__(self, kind: str, reason: str, retry_after: int | None = None):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason
        self.retry_after = retry_after


@dataclass
class SnapshotData:
    source_id: Any
    snapshot_id: Any
    url: str
    final_url: str
    fetched_at: datetime
    text: str
    title: str | None
    links: list[dict[str, str]]
    structured: dict[str, Any]
    content_type: str | None
    raw: bytes | None
    from_cache: bool = False
    fetched_now: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


def _snap_to_data(src: Source, snap: SourceSnapshot, *, from_cache: bool, fetched_now: bool) -> SnapshotData:
    raw = None
    if snap.raw_z:
        try:
            raw = zlib.decompress(snap.raw_z)
        except zlib.error:
            raw = None
    return SnapshotData(
        source_id=src.id, snapshot_id=snap.id, url=src.url, final_url=snap.final_url, fetched_at=snap.fetched_at,
        text=snap.text, title=snap.title, links=list(snap.links or []), structured=dict(snap.structured or {}),
        content_type=snap.content_type, raw=raw, from_cache=from_cache, fetched_now=fetched_now,
    )


async def get_or_create_source(url: str, kind: str = "page") -> Source:
    canon = canonicalize_url(url)
    async with session_scope() as s:
        await s.execute(
            pg_insert(Source).values(url=canon, domain=domain_of(canon), kind=kind).on_conflict_do_nothing(
                index_elements=["url"]
            )
        )
        src = (await s.execute(select(Source).where(Source.url == canon))).scalar_one()
        s.expunge(src)
        return src


async def _latest_snapshot(src_id: Any) -> tuple[Source, SourceSnapshot | None]:
    async with session_scope() as s:
        src = (await s.execute(select(Source).where(Source.id == src_id))).scalar_one()
        snap = None
        if src.last_snapshot_id:
            snap = await s.get(SourceSnapshot, src.last_snapshot_id)
        s.expunge(src)
        if snap is not None:
            s.expunge(snap)
        return src, snap


async def _domain_policy(domain: str) -> DomainPolicy | None:
    async with session_scope() as s:
        pol = await s.get(DomainPolicy, domain)
        if pol is not None:
            s.expunge(pol)
        return pol


async def _record_failure(src_id: Any, domain: str, kind: str, reason: str, retry_after: int | None,
                          status_code: int | None) -> int:
    now = datetime.now(UTC)
    async with session_scope() as s:
        src = await s.get(Source, src_id, with_for_update=True)
        assert src is not None
        src.consecutive_failures = (src.consecutive_failures or 0) + 1
        src.last_status_code = status_code
        src.status_reason = reason
        if kind == "gone" and src.consecutive_failures >= GONE_THRESHOLD:
            src.status = "gone"
        elif kind == "blocked":
            src.status = "blocked"
        elif kind not in ("busy",):
            src.status = "error" if src.consecutive_failures >= 3 else src.status
        if kind == "blocked":
            await s.execute(pg_insert(DomainPolicy).values(domain=domain).on_conflict_do_nothing())
            pol = await s.get(DomainPolicy, domain, with_for_update=True)
            assert pol is not None
            pol.block_count = (pol.block_count or 0) + 1
            backoff = retry_after or min(1800 * (2 ** min(pol.block_count - 1, 6)), 24 * 3600)
            pol.blocked_until = now + timedelta(seconds=backoff)
            pol.block_reason = reason
            if render_available() and src.fetch_mode == "http":
                pol.needs_render = True
                src.fetch_mode = "render"
        return src.consecutive_failures


async def _store_success(src_id: Any, res: FetchResult, ext_text: str, title: str | None, links: list[Any],
                         structured: dict[str, Any], chash: str) -> tuple[Source, SourceSnapshot, bool]:
    now = datetime.now(UTC)
    async with session_scope() as s:
        src = await s.get(Source, src_id, with_for_update=True)
        assert src is not None
        src.last_fetched_at = now
        src.last_status_code = res.status_code
        src.consecutive_failures = 0
        src.status = "active"
        src.status_reason = None
        src.etag = res.headers.get("etag")
        src.last_modified = res.headers.get("last-modified")
        created = False
        snap: SourceSnapshot | None = None
        if src.last_content_hash == chash and src.last_snapshot_id:
            snap = await s.get(SourceSnapshot, src.last_snapshot_id)
        if snap is None:
            raw_z = zlib.compress(res.content[:MAX_RAW_STORE], 6) if res.content else None
            snap = SourceSnapshot(
                source_id=src.id, status_code=res.status_code, final_url=res.final_url,
                content_type=res.content_type, content_hash=chash, simhash=simhash64(ext_text), title=title,
                text=ext_text, links=links, structured=structured, raw_z=raw_z, byte_size=len(res.content),
                fetch_ms=res.elapsed_ms,
            )
            s.add(snap)
            await s.flush()
            src.last_snapshot_id = snap.id
            src.last_content_hash = chash
            created = True
        # domain recovered
        pol = await s.get(DomainPolicy, src.domain)
        if pol is not None and pol.blocked_until is not None:
            pol.blocked_until = None
            pol.block_count = 0
        await s.flush()
        s.expunge(src)
        s.expunge(snap)
        return src, snap, created


async def _touch(src_id: Any, res: FetchResult) -> None:
    async with session_scope() as s:
        src = await s.get(Source, src_id, with_for_update=True)
        assert src is not None
        src.last_fetched_at = datetime.now(UTC)
        src.last_status_code = res.status_code
        src.consecutive_failures = 0
        src.status = "active"


async def fetch_source(url: str, *, max_age_seconds: int = 300, kind: str = "page",
                       force_render: bool = False, lock_wait_seconds: float = 20.0) -> SnapshotData:
    src = await get_or_create_source(url, kind)
    now = datetime.now(UTC)

    pol = await _domain_policy(src.domain)
    if pol is not None:
        if pol.denylisted:
            raise SourceUnavailable("blocked", "This site is not allowed on Watchtower")
        if pol.blocked_until and pol.blocked_until > now:
            raise SourceUnavailable(
                "blocked", pol.block_reason or "Site is temporarily blocking us",
                int((pol.blocked_until - now).total_seconds()),
            )

    src, snap = await _latest_snapshot(src.id)
    if snap is not None and src.last_fetched_at and (now - src.last_fetched_at).total_seconds() < max_age_seconds:
        FETCH_TOTAL.labels(result="reused").inc()
        return _snap_to_data(src, snap, from_cache=True, fetched_now=False)

    lock = RedisLock(f"lock:src:{src.id}", ttl_ms=60_000)
    if not await lock.acquire():
        waited = 0.0
        while waited < lock_wait_seconds:
            await asyncio.sleep(0.5)
            waited += 0.5
            src2, snap2 = await _latest_snapshot(src.id)
            if snap2 is not None and src2.last_fetched_at and src2.last_fetched_at >= now:
                FETCH_TOTAL.labels(result="singleflight").inc()
                return _snap_to_data(src2, snap2, from_cache=True, fetched_now=False)
            if not await lock.acquire():
                continue
            break
        else:
            if snap is not None:
                return _snap_to_data(src, snap, from_cache=True, fetched_now=False)
            raise SourceUnavailable("busy", "Another worker is fetching this page; retrying shortly", 30)
    try:
        # double-checked: another worker may have fetched between our freshness check and taking the lock
        src, snap = await _latest_snapshot(src.id)
        if snap is not None and src.last_fetched_at and \
                (datetime.now(UTC) - src.last_fetched_at).total_seconds() < max_age_seconds:
            FETCH_TOTAL.labels(result="singleflight").inc()
            return _snap_to_data(src, snap, from_cache=True, fetched_now=False)
        try:
            robots = await check_robots(src.url)
        except FetchError as e:
            await _record_failure(src.id, src.domain, e.code, str(e), None, None)
            raise SourceUnavailable(e.code, str(e)) from e
        if not robots.allowed:
            await _record_failure(src.id, src.domain, "robots", robots.reason, None, None)
            raise SourceUnavailable("robots", robots.reason)
        try:
            await acquire_domain_slot(src.domain, max(robots.crawl_delay or 0, (pol.min_interval_seconds or 0) if pol else 0))
        except DomainBusy as e:
            raise SourceUnavailable("busy", "Site rate limit reached; retrying shortly", int(e.wait_seconds) + 1) from e

        use_render = force_render or src.fetch_mode == "render" or (pol is not None and pol.needs_render)
        with FETCH_DURATION.time():
            try:
                if use_render and render_available():
                    res = await render_page(src.url)
                else:
                    res = await safe_fetch(
                        src.url,
                        etag=src.etag if snap is not None else None,
                        last_modified=src.last_modified if snap is not None else None,
                    )
            except FetchError as e:
                FETCH_TOTAL.labels(result=e.code).inc()
                await _record_failure(src.id, src.domain, e.code, str(e), None, None)
                raise SourceUnavailable(e.code, str(e)) from e

        if res.status_code == 304 and snap is not None:
            await _touch(src.id, res)
            FETCH_TOTAL.labels(result="not_modified").inc()
            src, snap = await _latest_snapshot(src.id)
            assert snap is not None
            return _snap_to_data(src, snap, from_cache=False, fetched_now=True)

        body_head = res.content[:20000].decode("utf-8", "ignore")
        ext = None
        if res.status_code < 400:
            try:
                ext = extract(res.content, res.content_type, res.encoding, res.final_url)
            except Exception as e:  # malformed content must never crash a worker
                log.warning("extract_failed", url=src.url, error=str(e))
                ext = None
        cls = classify_response(res.status_code, res.headers, body_head, len(ext.text) if ext else 0)
        if cls.kind != "ok" or ext is None:
            kind = cls.kind if cls.kind != "ok" else "fetch_error"
            reason = cls.reason if cls.kind != "ok" else "Could not read page content"
            FETCH_TOTAL.labels(result=kind).inc()
            await _record_failure(src.id, src.domain, kind, reason, cls.retry_after, res.status_code)
            raise SourceUnavailable(kind, reason, cls.retry_after)

        chash = content_hash(ext.text)
        src2, snap2, created = await _store_success(
            src.id, res, ext.text, ext.title, ext.links, ext.structured, chash
        )
        FETCH_TOTAL.labels(result="changed" if created else "unchanged").inc()
        data = _snap_to_data(src2, snap2, from_cache=False, fetched_now=True)
        if data.raw is None and res.content:
            data.raw = res.content
        return data
    finally:
        await lock.release()


def view_for(snapshot: SnapshotData, selector: str | None) -> tuple[str, list[dict[str, str]], bool | None]:
    """The watch-specific view of a shared snapshot (CSS selector applied when present)."""
    if selector and snapshot.raw and (snapshot.content_type or "").find("html") >= 0:
        try:
            ext = extract_html(decode_body(snapshot.raw, None), snapshot.final_url, selector=selector)
            return ext.text, ext.links, ext.selector_matched
        except Exception:
            return snapshot.text, snapshot.links, False
    return snapshot.text, snapshot.links, None if not selector else False
