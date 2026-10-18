import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.agents.act import act_on_alert
from app.core.db import session_scope
from app.core.redis import get_redis
from app.models import Alert, AlertDelivery, Check, IntakeSession, ProposedAction, Run, Watch
from app.workers import maintenance
from app.workers.checks import backoff_time, next_time, run_check
from app.workers.queue import Q_CHECKS
from app.workers.scheduler import tick
from tests.conftest import drain
from tests.helpers import get_check, get_watch, make_watch


async def make_due(n: int) -> None:
    async with session_scope() as s:
        await s.execute(update(Check).values(next_run_at=datetime.now(UTC) - timedelta(seconds=5)))
    _ = n


async def test_scheduler_claims_once_across_concurrent_ticks(make_user, site) -> None:  # noqa: ANN001
    u = await make_user(plan="pro")
    url = site.set("site.test", "/s", "<p>x</p>")
    for i in range(12):
        await make_watch(u, {"sources": [{"url": f"{url}?i={i}"}], "condition": "anything new"})
    await make_due(12)
    claimed = await asyncio.gather(*(tick() for _ in range(4)))  # 4 schedulers racing
    assert sum(claimed) == 12
    from redis.asyncio import Redis

    from tests.conftest import TEST_REDIS

    raw = Redis.from_url(TEST_REDIS)
    assert await raw.zcard(Q_CHECKS) == 12
    await raw.aclose()
    assert await tick() == 0


async def test_expired_lease_is_reclaimed(make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    await make_watch(u, {"sources": [{"url": site.set("site.test", "/l", "<p>x</p>")}], "condition": "abc"})
    await make_due(1)
    assert await tick() == 1
    async with session_scope() as s:
        await s.execute(update(Check).values(lease_until=datetime.now(UTC) - timedelta(seconds=1)))
    assert await tick() == 1  # worker died: lease expired, claimed again


async def test_stale_lease_token_is_ignored(make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/t", "<p>x</p>")}], "condition": "abc"})
    chk = await get_check(wid)
    assert (await run_check({}, str(chk.id), "wrong-token")) == {"skipped": "lease_lost"}


async def test_failures_back_off_and_escalate_then_self_heal(make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user(email="o@example.com")
    url = site.url("news.test", "/flaky")
    wid = await make_watch(u, {"sources": [{"url": url}], "condition": "abc"})
    for i in range(5):
        await make_due(1)
        assert await tick() == 1
        out = await drain(("checks",))
        assert out[0][1]["outcome"] == "error"
        chk = await get_check(wid)
        assert chk.consecutive_failures == i + 1
        assert chk.next_run_at > datetime.now(UTC) + timedelta(minutes=50)  # exponential backoff
    w = await get_watch(wid)
    assert w.status == "error" and "Paused after 5 failed checks" in w.status_reason
    async with session_scope() as s:
        d = (await s.execute(select(AlertDelivery).where(AlertDelivery.kind == "system"))).scalars().all()
        assert len(d) == 1 and "Watch paused" in d[0].payload["title"]
    # the site comes back: next (slow) probe succeeds and the watch reactivates itself
    site.set("news.test", "/flaky", "<html><body>back</body></html>")
    async with session_scope() as s:
        await s.execute(update(Check).values(next_run_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert await tick() == 1
    await drain(("checks",))
    assert (await get_watch(wid)).status == "active"
    assert (await get_check(wid)).consecutive_failures == 0


def test_next_time_jitter_and_backoff_bounds() -> None:
    now = datetime.now(UTC)
    for _ in range(50):
        t = next_time(3600, now=now)
        assert timedelta(seconds=3240) <= t - now <= timedelta(seconds=3960)
    assert backoff_time(3600, 1, None, now=now) - now >= timedelta(seconds=3200)
    assert backoff_time(3600, 20, None, now=now) - now <= timedelta(hours=26.5)
    assert backoff_time(900, 1, 7200, now=now) - now >= timedelta(seconds=6400)


async def test_paused_and_expired_watches_are_not_run(client, auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    url = site.set("site.test", "/p", "<p>x</p>")
    wid = await make_watch(u, {"sources": [{"url": url}], "condition": "abc"})
    assert (await client.post(f"/v1/watches/{wid}/pause", headers=h)).json()["status"] == "paused"
    await make_due(1)
    assert await tick() == 0  # disabled check
    assert (await client.post(f"/v1/watches/{wid}/resume", headers=h)).json()["status"] == "active"
    wid2 = await make_watch(u, {"sources": [{"url": url}], "condition": "abc",
                                "expires_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat()})
    await asyncio.sleep(1.2)
    chk = await get_check(wid2)
    async with session_scope() as s:
        await s.execute(update(Check).where(Check.id == chk.id).values(lease_token="tok"))
    assert await run_check({}, str(chk.id), "tok") == {"skipped": "expired"}
    assert (await get_watch(wid2)).status == "expired"


async def _alert_for(u, site, act_status="pending") -> uuid.UUID:  # noqa: ANN001
    url = site.set("gov.test", "/act", "<html><body><p>Admit card out. Exam on 20 Dec 2026.</p>"
                   "<a href='/admit'>Download admit card</a></body></html>")
    wid = await make_watch(u, {"kind": "exam_notification", "sources": [{"url": url}], "condition": "admit card out"})
    from app.agents.evaluate import run_evaluation

    await run_evaluation(wid)  # baseline: also stores the page view + links used by Act
    async with session_scope() as s:
        a = Alert(watch_id=wid, fingerprint=uuid.uuid4().hex, title="Admit card out", summary="Admit cards released",
                  source_url=url, act_status=act_status, evidence="Admit card out",
                  context_excerpt="Admit card out. Exam on 20 Dec 2026.")
        s.add(a)
        await s.flush()
        return a.id


async def test_act_grounds_links_and_dates(make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user()
    aid = await _alert_for(u, site)
    llm.on("act", {"headline": "Admit card released", "what_happened": "Download it now.",
                   "key_details": [{"name": "Exam date", "value": "20 Dec 2026"}],
                   "deadlines": [{"label": "Exam", "date": "2026-12-20", "evidence_quote": "Exam on 20 Dec 2026"},
                                 {"label": "Invented", "date": "2026-11-11", "evidence_quote": "results on 11 Nov"},
                                 {"label": "Past", "date": "2001-01-01", "evidence_quote": "Admit card out"}],
                   "important_links": [{"name": "Download admit card", "value": site.url("gov.test", "/admit")},
                                       {"name": "Phish", "value": "https://evil.example/admit"}],
                   "checklist": ["Print admit card"], "followup_watch_suggestion": "SSC result for this exam"})
    res = await act_on_alert({}, str(aid))
    assert res["status"] == "completed"
    async with session_scope() as s:
        a = await s.get(Alert, aid)
        assert [d["label"] for d in a.act_result["deadlines"]] == ["Exam"]
        assert [link["name"] for link in a.act_result["links"]] == ["Download admit card"]
        kinds = sorted(x.kind for x in (await s.execute(select(ProposedAction))).scalars())
    assert kinds == ["add_to_calendar", "create_followup_watch", "open_link", "set_reminder"]
    assert any(n == "fanout_alert" for n, _ in await drain(("notify",), only={"fanout_alert"}))
    assert (await act_on_alert({}, str(aid)))["status"] == "completed"  # idempotent re-run


async def test_act_quota_and_failure_still_notify(make_user, site, llm) -> None:  # noqa: ANN001
    from app.services.plans import consume

    u = await make_user()
    aid = await _alert_for(u, site)
    async with session_scope() as s:
        await consume(s, u.id, "acts", "month", 20, amount=20)
    res = await act_on_alert({}, str(aid))
    assert res["status"] == "skipped"
    async with session_scope() as s:
        assert "limit" in (await s.get(Alert, aid)).act_result["note"]
    u2 = await make_user()
    aid2 = await _alert_for(u2, site)
    from app.llm.client import LLMUnavailable

    llm.fail_with = LLMUnavailable("down")
    res = await act_on_alert({}, str(aid2))
    assert res["status"] == "failed"
    out = await drain(("notify",))
    assert any(n == "send_delivery" for n, _ in out)  # the alert still goes out


async def test_sweeper_redrives_lost_jobs(make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user()
    await _alert_for(u, site)
    async with session_scope() as s:
        await s.execute(update(Alert).values(created_at=datetime.now(UTC) - timedelta(minutes=10)))
    res = await maintenance.sweep_stuck({})
    assert res["acts"] == 1
    llm.on("act", {"headline": "h", "what_happened": "w"})
    out = await drain(("agents",))
    assert out and out[0][0] == "act_on_alert"


async def test_retention_and_stats_flush(make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/ret", "<p>x</p>")}], "condition": "abc"})
    async with session_scope() as s:
        s.add(Run(watch_id=wid, status="completed", outcome="no_match", started_at=datetime.now(UTC) - timedelta(days=40)))
        s.add(Run(watch_id=wid, status="completed", outcome="no_match"))
        s.add(IntakeSession(user_id=u.id, query="old", status="proposed",
                            updated_at=datetime.now(UTC) - timedelta(days=8)))
    out = await maintenance.retention({})
    assert out["runs"] == 1  # free plan keeps 30 days
    async with session_scope() as s:
        assert len((await s.execute(select(Run))).scalars().all()) == 1
    assert await maintenance.expire_intake({}) == 1
    from app.llm.client import record_usage

    await record_usage("openai/gpt-oss-120b", "judge", 1000, 200, 0.00027)
    assert await maintenance.flush_llm_stats({}) == 1
    assert await maintenance.flush_llm_stats({}) == 1  # idempotent (absolute values)
    from app.models import LlmUsageDaily

    async with session_scope() as s:
        row = (await s.execute(select(LlmUsageDaily))).scalar_one()
        assert row.calls == 1 and row.prompt_tokens == 1000
    _ = (get_redis, Watch)
