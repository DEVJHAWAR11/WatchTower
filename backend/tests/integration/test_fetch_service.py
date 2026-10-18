import asyncio

import pytest
from sqlalchemy import select

from app.core.db import session_scope
from app.fetch.service import SourceUnavailable, fetch_source, view_for
from app.models import DomainPolicy, Source, SourceSnapshot


async def test_fetch_reuse_and_conditional_get(site) -> None:  # noqa: ANN001
    url = site.set("site.test", "/p", "<html><body><h1>Hello</h1></body></html>", headers={"ETag": '"v1"'})
    a = await fetch_source(url, max_age_seconds=300)
    assert "Hello" in a.text and a.fetched_now
    b = await fetch_source(url, max_age_seconds=300)
    assert b.from_cache and b.snapshot_id == a.snapshot_id
    assert site.hits["site.test/p"] == 1
    c = await fetch_source(url, max_age_seconds=0)  # forces network; server answers 304
    assert c.snapshot_id == a.snapshot_id
    assert site.hits["site.test/p"] == 2
    assert any(r["headers"].get("If-None-Match") == '"v1"' for r in site.requests)


async def test_unchanged_body_does_not_create_snapshot(site) -> None:  # noqa: ANN001
    url = site.set("site.test", "/same", "<html><body>Same content 10:30 AM</body></html>")
    a = await fetch_source(url, max_age_seconds=0)
    site.set("site.test", "/same", "<html><body>Same content 11:45 AM</body></html>")
    b = await fetch_source(url, max_age_seconds=0)
    assert a.snapshot_id == b.snapshot_id  # only a volatile clock changed
    async with session_scope() as s:
        n = len((await s.execute(select(SourceSnapshot))).scalars().all())
    assert n == 1


async def test_single_flight(site) -> None:  # noqa: ANN001
    url = site.set("site.test", "/slow", "<html><body>slow page</body></html>", delay=0.6)
    results = await asyncio.gather(*[fetch_source(url, max_age_seconds=300) for _ in range(6)])
    assert all("slow page" in r.text for r in results)
    assert site.hits["site.test/slow"] == 1


async def test_robots_disallow(site) -> None:  # noqa: ANN001
    site.set("gov.test", "/robots.txt", "User-agent: *\nDisallow: /private", headers={"Content-Type": "text/plain"})
    url = site.set("gov.test", "/private/x", "<html><body>secret</body></html>")
    with pytest.raises(SourceUnavailable) as e:
        await fetch_source(url, max_age_seconds=0)
    assert e.value.kind == "robots"
    ok = site.set("gov.test", "/public", "<html><body>fine</body></html>")
    assert "fine" in (await fetch_source(ok, max_age_seconds=0)).text


async def test_blocked_site_backs_off_without_hammering(site) -> None:  # noqa: ANN001
    url = site.set("blocked.test", "/x", "<html><title>Just a moment...</title>cf-chl-bypass</html>", status=503)
    with pytest.raises(SourceUnavailable) as e:
        await fetch_source(url, max_age_seconds=0)
    assert e.value.kind == "blocked"
    with pytest.raises(SourceUnavailable):
        await fetch_source(url, max_age_seconds=0)
    assert site.hits["blocked.test/x"] == 1  # second call never reached the network
    async with session_scope() as s:
        pol = await s.get(DomainPolicy, "blocked.test")
        assert pol is not None and pol.blocked_until is not None and pol.block_count == 1


async def test_gone_after_repeated_404(site) -> None:  # noqa: ANN001
    url = site.url("news.test", "/removed")
    for _ in range(3):
        with pytest.raises(SourceUnavailable) as e:
            await fetch_source(url, max_age_seconds=0)
        assert e.value.kind == "gone"
    async with session_scope() as s:
        src = (await s.execute(select(Source).where(Source.url.like("%/removed")))).scalar_one()
        assert src.status == "gone"


async def test_selector_view(site) -> None:  # noqa: ANN001
    url = site.set("site.test", "/sel", "<html><body><div id='a'>Alpha</div><div id='b'>Beta</div></body></html>")
    snap = await fetch_source(url, max_age_seconds=0)
    text, _, matched = view_for(snap, "#b")
    assert text == "Beta" and matched is True
    text2, _, matched2 = view_for(snap, "#zzz")
    assert "Alpha" in text2 and matched2 is False
