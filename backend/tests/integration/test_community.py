from sqlalchemy import select, update

from app.agents.evaluate import run_evaluation
from app.core.db import session_scope
from app.models import Plan, Subscription, Watch
from app.services.plans import invalidate_plan_cache
from tests.conftest import drain, emails
from tests.helpers import keyword_judge, make_watch

SPEC = {"kind": "exam_result", "sources": [{"url": "http://gov.test/ssc"}],
        "condition": "SSC CGL 2026 final result is declared", "keywords": ["result"]}


def spec_for(site) -> dict:  # noqa: ANN001
    s = dict(SPEC)
    s["sources"] = [{"url": site.set("gov.test", "/ssc", "<html><body><p>Notices</p></body></html>")}]
    return s


async def publish(client, h, wid, llm, decision="approve") -> dict:  # noqa: ANN001
    llm.on("moderation", {"decision": decision, "category": "ok" if decision == "approve" else "spam", "reason": "x"})
    r = await client.patch(f"/v1/watches/{wid}", headers=h, json={"visibility": "public"})
    assert r.status_code == 200, r.text
    await drain(("agents",), only={"moderate_watch"})
    return (await client.get(f"/v1/watches/{wid}", headers=h)).json()


async def test_publish_explore_subscribe_and_shared_alerts(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    owner = await make_user(email="owner@example.com")
    fan = await make_user(email="fan@example.com")
    stranger = await make_user(email="s@example.com")
    wid = await make_watch(owner, spec_for(site), title="SSC CGL 2026 result")
    w = await publish(client, auth(owner), wid, llm)
    assert w["visibility"] == "public" and w["moderation_status"] == "approved"

    ex = (await client.get("/v1/explore?q=ssc cgl")).json()
    assert [x["id"] for x in ex["items"]] == [str(wid)]
    assert ex["items"][0]["owner"]["handle"] is None
    cats = {c["slug"]: c["watch_count"] for c in (await client.get("/v1/explore/categories")).json()}
    assert cats["other"] == 1
    assert (await client.get(f"/v1/explore/watches/{w['slug']}")).status_code == 200

    r = await client.post(f"/v1/watches/{wid}/subscribe", headers=auth(fan), json={"delivery_mode": "instant"})
    assert r.status_code == 200 and r.json()["is_subscribed"] and r.json()["subscriber_count"] == 2
    again = await client.post(f"/v1/watches/{wid}/subscribe", headers=auth(fan))
    assert again.json()["subscriber_count"] == 2  # idempotent
    assert (await client.post(f"/v1/watches/{wid}/subscribe", headers=auth(owner))).status_code == 409

    # one check serves every subscriber
    await run_evaluation(wid)
    site.set("gov.test", "/ssc", "<html><body><p>Notices</p><p>SSC CGL 2026 final result declared</p></body></html>")
    llm.on("judge", keyword_judge("final result", event_key="ssc cgl 2026 final result"))
    llm.on("act", {"headline": "SSC CGL 2026 result is out", "what_happened": "Declared.", "key_details": [],
                   "deadlines": [], "important_links": [], "checklist": [], "comparison": "", "draft_message": "",
                   "followup_watch_suggestion": ""})
    res = await run_evaluation(wid, trigger="manual")
    assert res["outcome"] == "matched"
    from app.workers.queue import Q_AGENTS, enqueue

    await enqueue("act_on_alert", res["alert_id"], queue=Q_AGENTS, job_id="a1")
    await drain(("agents", "notify"))
    to = sorted(m["to"] for m in await emails())
    assert to == ["fan@example.com", "owner@example.com"]
    assert llm.count("judge") == 1 and llm.count("act") == 1

    # subscriber sees it in their inbox; a stranger can still view a public watch but not get alerts
    inbox = (await client.get("/v1/alerts", headers=auth(fan))).json()
    assert len(inbox["items"]) == 1
    assert (await client.get(f"/v1/watches/{wid}/state", headers=auth(stranger))).status_code == 200
    st = (await client.get(f"/v1/watches/{wid}/state", headers=auth(stranger))).json()
    assert st["current_version"] is None  # spec details are owner-only

    assert (await client.delete(f"/v1/watches/{wid}/subscribe", headers=auth(fan))).status_code == 204
    assert (await client.get(f"/v1/watches/{wid}", headers=auth(owner))).json()["subscriber_count"] == 1


async def test_moderation_rules_and_reports(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    owner = await make_user()
    spam = await make_watch(owner, spec_for(site), title="Earn $500 daily work from home earn guaranteed returns")
    w = await publish(client, auth(owner), spam, llm, decision="approve")
    assert w["moderation_status"] == "rejected" and w["visibility"] == "private"  # rules beat the LLM
    assert llm.count("moderation") == 0

    good = await make_watch(owner, spec_for(site), title="UPSC CSE 2026 notification")
    await publish(client, auth(owner), good, llm)
    reporters = [await make_user() for _ in range(3)]
    for i, rep in enumerate(reporters):
        r = await client.post(f"/v1/watches/{good}/report", headers=auth(rep), json={"reason": "spam"})
        assert r.status_code == 200
        assert r.json()["hidden"] == (i == 2)
    dup = await client.post(f"/v1/watches/{good}/report", headers=auth(reporters[0]), json={"reason": "spam"})
    assert dup.json()["status"] == "already_reported"
    assert (await client.get("/v1/explore?q=upsc")).json()["items"] == []
    assert (await client.post(f"/v1/watches/{good}/report", headers=auth(owner), json={"reason": "spam"})).status_code == 409


async def test_visibility_rules(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    unverified = await make_user(verified=False)
    wid = await make_watch(unverified, spec_for(site))
    r = await client.patch(f"/v1/watches/{wid}", headers=auth(unverified, verified=False), json={"visibility": "public"})
    assert r.status_code == 403 and "Verify your email" in r.json()["error"]["message"]

    owner = await make_user()
    other = await make_user()
    wid2 = await make_watch(owner, spec_for(site), title="Unlisted thing")
    r = await client.patch(f"/v1/watches/{wid2}", headers=auth(owner), json={"visibility": "unlisted"})
    assert r.json()["visibility"] == "unlisted"
    assert (await client.get(f"/v1/watches/{wid2}", headers=auth(other))).status_code == 200
    assert (await client.get("/v1/explore?q=unlisted")).json()["items"] == []
    r = await client.post(f"/v1/watches/{wid2}/subscribe", headers=auth(other))
    assert r.status_code == 200
    # owner cannot pull a shared watch out from under subscribers
    assert (await client.delete(f"/v1/watches/{wid2}", headers=auth(owner))).status_code == 409


async def test_subscription_quota_and_fork(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    async with session_scope() as s:
        p = await s.get(Plan, "free")
        p.limits = {**p.limits, "max_subscriptions": 1}
    invalidate_plan_cache()
    try:
        owner = await make_user()
        fan = await make_user()
        a = await make_watch(owner, spec_for(site), title="Watch A")
        b = await make_watch(owner, spec_for(site), title="Watch B")
        for wid in (a, b):
            await publish(client, auth(owner), wid, llm)
        assert (await client.post(f"/v1/watches/{a}/subscribe", headers=auth(fan))).status_code == 200
        r = await client.post(f"/v1/watches/{b}/subscribe", headers=auth(fan))
        assert r.status_code == 402 and r.json()["error"]["details"]["metric"] == "max_subscriptions"
        f = await client.post(f"/v1/watches/{b}/fork", headers=auth(fan))
        assert f.status_code == 201 and f.json()["is_owner"] and f.json()["visibility"] == "private"
    finally:
        async with session_scope() as s:
            p = await s.get(Plan, "free")
            p.limits = {**p.limits, "max_subscriptions": 25}
        invalidate_plan_cache()


async def test_account_deletion_hands_public_watch_to_community(client, auth, make_user, site, llm, respx_mock) -> None:  # noqa: ANN001
    from httpx import Response

    owner = await make_user()
    fan = await make_user()
    wid = await make_watch(owner, spec_for(site), title="NEET UG 2026 result")
    await publish(client, auth(owner), wid, llm)
    await client.post(f"/v1/watches/{wid}/subscribe", headers=auth(fan))
    private = await make_watch(owner, spec_for(site), title="my private")
    respx_mock.delete(url__regex=r"https://proj\.supabase\.co/auth/v1/admin/users/.*").mock(return_value=Response(200))
    assert (await client.delete("/v1/me?confirm=nope", headers=auth(owner))).status_code == 409
    r = await client.delete("/v1/me?confirm=DELETE", headers=auth(owner))
    assert r.status_code == 202, r.text
    async with session_scope() as s:
        w = await s.get(Watch, wid)
        assert str(w.owner_id) == "00000000-0000-0000-0000-000000000001"
        assert await s.get(Watch, private) is None
        subs = (await s.execute(select(Subscription).where(Subscription.watch_id == wid))).scalars().all()
        assert {str(x.user_id) for x in subs} == {str(fan.id), "00000000-0000-0000-0000-000000000001"}
    assert (await client.get(f"/v1/watches/{wid}", headers=auth(fan))).json()["owner"]["is_community"] is True
    _ = update
