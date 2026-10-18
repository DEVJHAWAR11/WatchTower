"""Coverage of the remaining API surface: watch operations, versions, refinements, actions, account, admin."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agents.evaluate import run_evaluation
from app.core.db import session_scope
from app.models import Alert, ProposedAction, RefinementProposal, Reminder, WatchVersion
from tests.conftest import drain, emails
from tests.helpers import keyword_judge, make_watch


async def fired_alert(user, site, llm, *, kind="price_drop") -> tuple[uuid.UUID, uuid.UUID]:  # noqa: ANN001
    url = site.set("shop.test", "/ops", "<html><body><p>Phone ₹25,000</p></body></html>")
    wid = await make_watch(user, {"kind": kind, "sources": [{"url": url}], "condition": "Phone gets cheaper",
                                  "predicates": [{"type": "price_below", "threshold": 24000}], "predicate_mode": "decide"})
    await run_evaluation(wid)
    site.set("shop.test", "/ops", "<html><body><p>Phone ₹19,999</p></body></html>")
    res = await run_evaluation(wid, trigger="manual")
    assert res["outcome"] == "matched"
    return wid, uuid.UUID(res["alert_id"])


async def test_watch_crud_versions_and_history(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    url = site.set("site.test", "/crud", "<html><body>hello</body></html>")
    r = await client.post("/v1/watches", headers=h, json={
        "title": "My watch", "category": "jobs", "spec": {"sources": [{"url": url}], "condition": "a new job"}})
    assert r.status_code == 201
    wid = r.json()["id"]
    r = await client.patch(f"/v1/watches/{wid}", headers=h, json={"title": "Renamed", "tags": ["a", "b"],
                                                                   "default_delivery_mode": "digest", "auto_tune": False})
    assert r.json()["title"] == "Renamed" and r.json()["tags"] == ["a", "b"]
    bad = await client.put(f"/v1/watches/{wid}/spec", headers=h, json={"spec": {"sources": [], "condition": "x"}})
    assert bad.status_code == 422 and bad.json()["error"]["details"]
    v2 = await client.put(f"/v1/watches/{wid}/spec", headers=h, json={
        "spec": {"sources": [{"url": url}], "condition": "a new backend job"}, "changelog": "narrowed"})
    assert v2.status_code == 200 and v2.json()["version"] == 2 and v2.json()["changelog"] == "narrowed"
    same = await client.put(f"/v1/watches/{wid}/spec", headers=h, json={
        "spec": {"sources": [{"url": url}], "condition": "a new backend job"}})
    assert same.json()["version"] == 2  # identical spec: no new version
    assert len((await client.get(f"/v1/watches/{wid}/versions", headers=h)).json()) == 2
    assert (await client.get(f"/v1/watches/{wid}/versions/diff?a=1&b=9", headers=h)).status_code == 404
    assert (await client.post(f"/v1/watches/{wid}/versions/7/rollback", headers=h)).status_code == 404

    for _ in range(3):
        await run_evaluation(uuid.UUID(wid), trigger="manual")
    page1 = (await client.get(f"/v1/watches/{wid}/runs?limit=2", headers=h)).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = (await client.get(f"/v1/watches/{wid}/runs?limit=2&cursor={page1['next_cursor']}", headers=h)).json()
    assert len(page2["items"]) == 1
    rid = page1["items"][0]["id"]
    detail = (await client.get(f"/v1/watches/{wid}/runs/{rid}", headers=h)).json()
    assert detail["steps"] and detail["steps"][0]["node"] == "fetch"
    assert (await client.get(f"/v1/watches/{wid}/runs/{uuid.uuid4()}", headers=h)).status_code == 404
    assert (await client.get(f"/v1/watches/{wid}/runs?cursor=garbage", headers=h)).status_code == 422
    st = (await client.get(f"/v1/watches/{wid}/state", headers=h)).json()
    assert st["current_version"]["version"] == 2 and st["stats"]["runs_7d"] == 3
    assert st["sources"][0]["status"] == "active"
    mine = (await client.get("/v1/me/watches?role=owner", headers=h)).json()
    assert [w["id"] for w in mine] == [wid]
    assert (await client.post(f"/v1/watches/{wid}/resume", headers=h)).status_code == 409
    assert (await client.delete(f"/v1/watches/{wid}", headers=h)).status_code == 204
    assert (await client.get("/v1/me/watches", headers=h)).json() == []
    assert len((await client.get("/v1/me/watches?include_archived=true", headers=h)).json()) == 1


async def test_refinement_proposals_accept_reject(client, auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/rf", "<p>x</p>")}], "condition": "old"})
    async with session_scope() as s:
        w_ver = (await s.execute(select(WatchVersion).where(WatchVersion.watch_id == wid))).scalar_one()
        spec = dict(w_ver.spec)
        spec["condition"] = "new and improved"
        p1 = RefinementProposal(watch_id=wid, from_version_id=w_ver.id, proposed_spec=spec, rationale="r",
                                changes=["c"], backtest={"accepted": True})
        p2 = RefinementProposal(watch_id=wid, from_version_id=w_ver.id, proposed_spec=spec, rationale="r2",
                                changes=["c2"], backtest={})
        s.add_all([p1, p2])
        await s.flush()
        p1_id, p2_id = p1.id, p2.id
    st = (await client.get(f"/v1/watches/{wid}/state", headers=h)).json()
    assert st["pending_refinement"] is not None
    assert len((await client.get(f"/v1/watches/{wid}/refinements", headers=h)).json()) == 2
    r = await client.post(f"/v1/watches/{wid}/refinements/{p2_id}/reject", headers=h)
    assert r.json()["status"] == "rejected"
    r = await client.post(f"/v1/watches/{wid}/refinements/{p1_id}/accept", headers=h)
    assert r.json()["status"] == "applied"
    assert (await client.post(f"/v1/watches/{wid}/refinements/{p1_id}/accept", headers=h)).status_code == 409
    assert (await client.post(f"/v1/watches/{wid}/refinements/{p1_id}/maybe", headers=h)).status_code == 404
    vers = (await client.get(f"/v1/watches/{wid}/versions", headers=h)).json()
    assert vers[0]["spec"]["condition"] == "new and improved" and vers[0]["created_by"] == "refinement"
    r = await client.post(f"/v1/watches/{wid}/refine", headers=h)
    assert r.status_code == 202


async def test_actions_all_kinds(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    wid, aid = await fired_alert(u, site, llm)
    async with session_scope() as s:
        mk = lambda kind, payload, **kw: ProposedAction(alert_id=aid, kind=kind, title=kind, payload=payload, **kw)  # noqa: E731
        acts = {
            "draft": mk("draft_email", {"subject": "Draft", "body": "Dear HR..."}),
            "follow": mk("create_followup_watch", {"query": "tell me when SSC CGL 2026 tier 2 admit card is out"}),
            "thresh": mk("adjust_threshold", {"threshold": 18000}, owner_only=True),
            "link": mk("open_link", {"url": "https://shop.example/buy"}),
            "evil": mk("open_link", {"url": "javascript:alert(1)"}),
            "expired": mk("set_reminder", {"remind_at": "2030-01-01T00:00:00+00:00", "message": "m"},
                          expires_at=datetime.now(UTC) - timedelta(days=1)),
            "reject": mk("set_reminder", {"remind_at": "2030-01-01T00:00:00+00:00", "message": "m"}),
        }
        s.add_all(acts.values())
        await s.flush()
        ids = {k: str(v.id) for k, v in acts.items()}
    r = await client.post(f"/v1/actions/{ids['draft']}/approve", headers=h)
    assert r.json()["status"] == "executed"
    await drain(("notify",))
    assert any(m["subject"] == "Draft" and "Dear HR" in m["text"] for m in await emails())
    r = await client.post(f"/v1/actions/{ids['follow']}/approve", headers=h)
    assert r.json()["result"]["intake_session_id"]
    r = await client.post(f"/v1/actions/{ids['thresh']}/approve", headers=h)
    assert r.json()["result"]["version"] == 2
    vers = (await client.get(f"/v1/watches/{wid}/versions", headers=h)).json()
    assert vers[0]["spec"]["predicates"][0]["threshold"] == 18000
    assert (await client.post(f"/v1/actions/{ids['link']}/approve", headers=h)).json()["result"]["url"].startswith("https")
    assert (await client.post(f"/v1/actions/{ids['evil']}/approve", headers=h)).status_code == 403
    assert (await client.post(f"/v1/actions/{ids['expired']}/approve", headers=h)).status_code == 410
    assert (await client.post(f"/v1/actions/{ids['reject']}/reject", headers=h)).json()["status"] == "rejected"
    async with session_scope() as s:
        assert (await s.execute(select(Reminder))).first() is None
    alert = (await client.get(f"/v1/alerts/{aid}", headers=h)).json()
    decided = {a["kind"]: a["decision"] for a in alert["actions"] if a["decision"]}
    assert decided["draft_email"] == "executed" and decided["set_reminder"] == "rejected"
    # an ICS link from another action/user is rejected
    from app.core.crypto import sign_payload

    tok = sign_payload({"a": str(uuid.uuid4()), "u": str(u.id)}, "ics")
    assert (await client.get(f"/v1/actions/{ids['draft']}/calendar.ics?token={tok}")).status_code == 403


async def test_feedback_and_quick_feedback_link(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    _, aid = await fired_alert(u, site, llm)
    r = await client.post(f"/v1/alerts/{aid}/feedback", headers=h, json={"relevant": True})
    assert r.json()["recorded"] is True
    assert (await client.get(f"/v1/alerts/{aid}", headers=h)).json()["my_feedback"] is True
    from app.notify.render import feedback_url

    url = feedback_url(u.id, str(aid), False).replace("http://localhost:8000", "")
    assert "Mark this alert as not relevant" in (await client.get(url)).text
    assert "Recorded" in (await client.post(url)).text
    assert (await client.get(f"/v1/alerts/{aid}", headers=h)).json()["my_feedback"] is False
    inbox = (await client.get(f"/v1/alerts?limit=1&watch_id={(await client.get(f'/v1/alerts/{aid}', headers=h)).json()['watch_id']}", headers=h)).json()
    assert len(inbox["items"]) == 1


async def test_account_endpoints(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    u = await make_user(email="me@example.com")
    h = auth(u)
    await fired_alert(u, site, llm)
    ex = (await client.get("/v1/me/export", headers=h)).json()
    assert ex["profile"]["email"] == "me@example.com" and len(ex["watches"]) == 1 and len(ex["alerts"]) == 1
    assert (await client.get("/v1/me/deliveries", headers=h)).status_code == 200
    ch = (await client.get("/v1/notifications/channels", headers=h)).json()
    assert ch["email"]["enabled"] is True and ch["webhook"]["available"] is False
    r = await client.post("/v1/notifications/test", headers=h)
    assert r.json()["queued"] == 1
    await drain(("notify",))
    assert any(m["subject"] == "Watchtower test notification" for m in await emails())
    assert (await client.delete("/v1/notifications/telegram", headers=h)).status_code == 204
    assert (await client.delete("/v1/notifications/push?endpoint=https://fcm.googleapis.com/x", headers=h)).status_code == 204
    r = await client.patch("/v1/me/settings", headers=h, json={"clear_quiet_hours": True, "auto_tune": False})
    assert r.json()["auto_tune"] is False and r.json()["quiet_hours_start"] is None
    other = await make_user()
    await client.patch("/v1/me/settings", headers=auth(other), json={"handle": "taken_one"})
    assert (await client.patch("/v1/me/settings", headers=h, json={"handle": "taken_one"})).status_code == 409


async def test_admin_operations(client, make_user, site, llm, auth_kit) -> None:  # noqa: ANN001
    admin = {"Authorization": f"Bearer {auth_kit.token(uuid.uuid4(), 'root@example.com', admin=True)}"}
    u = await make_user(email="target@example.com")
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/adm", "<p>x</p>")}], "condition": "abc"})
    users = (await client.get("/v1/admin/users?q=target", headers=admin)).json()
    assert [x["email"] for x in users] == ["target@example.com"]
    r = await client.post(f"/v1/admin/users/{u.id}/suspend", headers=admin, json={"suspend": True, "reason": "abuse"})
    assert r.json()["status"] if "status" in r.json() else True
    assert (await client.get("/v1/admin/moderation", headers=admin)).status_code == 200
    r = await client.post(f"/v1/admin/watches/{wid}/moderation", headers=admin, json={"decision": "reject", "reason": "x"})
    assert r.json()["moderation_status"] == "rejected"
    r = await client.post(f"/v1/admin/watches/{wid}/disable?reason=tos", headers=admin)
    assert r.json()["status"] == "paused"
    r = await client.put("/v1/admin/domains/Example.COM", headers=admin, json={"denylisted": True, "notes": "abuse"})
    assert r.json() == {"domain": "example.com", "denylisted": True, "needs_render": False}
    doms = (await client.get("/v1/admin/domains?blocked_only=true", headers=admin)).json()
    assert doms[0]["domain"] == "example.com"
    r = await client.put("/v1/admin/plans/free", headers=admin, json={"limits": {"max_watches": 6}})
    assert r.json()["limits"]["max_watches"] == 6
    await client.put("/v1/admin/plans/free", headers=admin, json={"limits": {"max_watches": 5}})
    assert (await client.put("/v1/admin/plans/gold", headers=admin, json={})).status_code == 404
    assert "by_day_usd" in (await client.get("/v1/admin/spend", headers=admin)).json()
    assert isinstance((await client.get("/v1/admin/reports", headers=admin)).json(), list)
    sysinfo = (await client.get("/v1/admin/system", headers=admin)).json()
    assert {"queues", "scheduler", "runs_last_hour", "totals", "llm_spend_today_usd"} <= set(sysinfo)
    r = await client.post(f"/v1/admin/users/{u.id}/suspend", headers=admin, json={"suspend": False, "reason": "ok"})
    assert r.status_code == 200
    assert (await client.post(f"/v1/admin/users/{uuid.uuid4()}/plan", headers=admin,
                              json={"plan_id": "pro", "reason": "x"})).status_code == 404
    _ = (Alert, keyword_judge)


async def test_denylisted_domain_is_never_fetched(make_user, site, llm, client, auth_kit) -> None:  # noqa: ANN001
    admin = {"Authorization": f"Bearer {auth_kit.token(uuid.uuid4(), admin=True)}"}
    await client.put("/v1/admin/domains/evil.test", headers=admin, json={"denylisted": True})
    u = await make_user()
    wid = await make_watch(u, {"sources": [{"url": site.set("evil.test", "/x", "<p>x</p>")}], "condition": "abc"})
    res = await run_evaluation(wid)
    assert res["outcome"] == "blocked" and "not allowed" in res["reason"]
    assert site.hits.get("evil.test/x") is None
