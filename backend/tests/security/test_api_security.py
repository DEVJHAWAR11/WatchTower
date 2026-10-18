"""Abuse & attack scenarios against the public API."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import session_scope
from app.models import Watch
from tests.helpers import make_watch


def simple_spec(url: str) -> dict:
    return {"sources": [{"url": url}], "condition": "anything new appears"}


async def test_idor_private_watch_is_invisible(client, auth, make_user, site) -> None:  # noqa: ANN001
    alice, mallory = await make_user(), await make_user()
    wid = await make_watch(alice, simple_spec(site.set("site.test", "/a", "<p>x</p>")))
    h = auth(mallory)
    for method, path, body in [
        ("GET", f"/v1/watches/{wid}", None), ("GET", f"/v1/watches/{wid}/state", None),
        ("GET", f"/v1/watches/{wid}/runs", None), ("GET", f"/v1/watches/{wid}/alerts", None),
        ("PATCH", f"/v1/watches/{wid}", {"title": "pwned"}), ("DELETE", f"/v1/watches/{wid}", None),
        ("POST", f"/v1/watches/{wid}/run", None), ("POST", f"/v1/watches/{wid}/pause", None),
        ("GET", f"/v1/watches/{wid}/versions", None), ("PUT", f"/v1/watches/{wid}/spec", {"spec": simple_spec("https://a.com")}),
        ("POST", f"/v1/watches/{wid}/subscribe", None), ("POST", f"/v1/watches/{wid}/fork", None),
        ("POST", f"/v1/watches/{wid}/report", {"reason": "spam"}),
    ]:
        r = await client.request(method, path, headers=h, json=body)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    async with session_scope() as s:
        assert (await s.get(Watch, wid)).title == "Test watch"
    # unauthenticated
    assert (await client.get(f"/v1/watches/{wid}")).status_code == 404
    # random/invalid ids
    assert (await client.get(f"/v1/watches/{uuid.uuid4()}", headers=h)).status_code == 404
    assert (await client.get("/v1/watches/not-a-uuid", headers=h)).status_code == 422


async def test_idor_alerts_actions_intake(client, auth, make_user, site) -> None:  # noqa: ANN001
    from app.models import Alert, IntakeSession, ProposedAction

    alice, mallory = await make_user(), await make_user()
    wid = await make_watch(alice, simple_spec(site.set("site.test", "/b", "<p>x</p>")))
    async with session_scope() as s:
        a = Alert(watch_id=wid, fingerprint="f", title="t", summary="s", source_url="https://x.in", act_status="completed")
        s.add(a)
        await s.flush()
        act = ProposedAction(alert_id=a.id, kind="set_reminder", title="r",
                             payload={"remind_at": "2030-01-01T00:00:00+00:00", "message": "m"})
        s.add(act)
        sess = IntakeSession(user_id=alice.id, query="q", status="proposed")
        s.add(sess)
        await s.flush()
        aid, act_id, sid = a.id, act.id, sess.id
    h = auth(mallory)
    assert (await client.get(f"/v1/alerts/{aid}", headers=h)).status_code == 404
    assert (await client.post(f"/v1/alerts/{aid}/feedback", headers=h, json={"relevant": False})).status_code == 404
    assert (await client.post(f"/v1/actions/{act_id}/approve", headers=h)).status_code == 404
    assert (await client.get(f"/v1/intake/{sid}", headers=h)).status_code == 404
    assert (await client.post(f"/v1/intake/{sid}/confirm", headers=h, json={"confirm": True})).status_code == 404
    assert (await client.get("/v1/alerts", headers=h)).json()["items"] == []


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/admin", "http://169.254.169.254/latest/meta-data/iam", "file:///etc/passwd",
    "http://localhost/", "http://[::1]/", "gopher://x.com/", "http://10.0.0.8/", "http://metadata.google.internal/",
])
async def test_ssrf_via_watch_spec_rejected(client, auth, make_user, url) -> None:  # noqa: ANN001
    u = await make_user()
    r = await client.post("/v1/watches", headers=auth(u), json={"title": "x", "spec": simple_spec(url)})
    assert r.status_code == 422, r.text
    assert "not allowed" in r.text or "scheme" in r.text or "URL" in r.text


async def test_ssrf_via_dns_name_blocked_at_fetch(client, auth, make_user, llm) -> None:  # noqa: ANN001
    """A public-looking hostname that resolves to a private IP is refused at connect time."""
    u = await make_user()
    r = await client.post("/v1/watches", headers=auth(u), json={"title": "x", "spec": simple_spec("http://rebind.example.com/")})
    assert r.status_code == 201  # syntactically fine...
    from app.agents.evaluate import run_evaluation

    res = await run_evaluation(uuid.UUID(r.json()["id"]))
    assert res["outcome"] == "error" and llm.count() == 0  # ...but never fetched


async def test_watch_quota_and_concurrent_race(client, auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    url = site.set("site.test", "/q", "<p>x</p>")

    async def create(i: int) -> int:
        r = await client.post("/v1/watches", headers=h, json={"title": f"w{i}", "spec": simple_spec(url)})
        return r.status_code

    codes = await asyncio.gather(*(create(i) for i in range(9)))
    assert codes.count(201) == 5 and codes.count(402) == 4, codes
    async with session_scope() as s:
        assert await s.scalar(select(func.count()).select_from(Watch).where(Watch.owner_id == u.id)) == 5


async def test_plan_limits_on_spec(client, auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    url = site.set("site.test", "/p", "<p>x</p>")
    many = {"sources": [{"url": f"{url}?i={i}"} for i in range(3)], "condition": "abc def"}
    r = await client.post("/v1/watches", headers=h, json={"title": "x", "spec": many})
    assert r.status_code == 402 and r.json()["error"]["details"]["metric"] == "max_sources_per_watch"
    fast = {**simple_spec(url), "interval_seconds": 300}
    r = await client.post("/v1/watches", headers=h, json={"title": "fast", "spec": fast})
    assert r.status_code == 201
    v = (await client.get(f"/v1/watches/{r.json()['id']}/versions", headers=h)).json()[0]
    assert v["spec"]["interval_seconds"] == 21600  # clamped to the free plan minimum


async def test_run_now_daily_quota(client, auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    wid = await make_watch(u, simple_spec(site.set("site.test", "/r", "<p>x</p>")))
    codes = [(await client.post(f"/v1/watches/{wid}/run", headers=h)).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 402]


async def test_api_tokens_pro_only_and_revocable(client, auth, make_user) -> None:  # noqa: ANN001
    free = await make_user()
    assert (await client.post("/v1/me/api-tokens", headers=auth(free), json={"name": "ci"})).status_code == 403
    pro = await make_user(plan="pro")
    r = await client.post("/v1/me/api-tokens", headers=auth(pro), json={"name": "ci"})
    assert r.status_code == 200
    token, tid = r.json()["token"], r.json()["token_info"]["id"]
    assert token.startswith("wt_")
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["id"] == str(pro.id)
    listed = (await client.get("/v1/me/api-tokens", headers=auth(pro))).json()
    assert "token" not in listed[0] and listed[0]["prefix"] == token[:10]
    assert (await client.delete(f"/v1/me/api-tokens/{tid}", headers=auth(pro))).status_code == 204
    assert (await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
    assert (await client.get("/v1/me", headers={"Authorization": "Bearer wt_guessed"})).status_code == 401


async def test_admin_endpoints_forbidden_for_users(client, auth, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    for path in ("/v1/admin/system", "/v1/admin/users", "/v1/admin/spend", "/v1/admin/moderation", "/v1/admin/audit"):
        assert (await client.get(path, headers=auth(u))).status_code == 403
    r = await client.post(f"/v1/admin/users/{u.id}/plan", headers=auth(u), json={"plan_id": "pro", "reason": "x"})
    assert r.status_code == 403


async def test_admin_manual_billing_is_audited(client, auth, make_user, auth_kit) -> None:  # noqa: ANN001
    u = await make_user()
    admin = {"Authorization": f"Bearer {auth_kit.token(uuid.uuid4(), admin=True)}"}
    r = await client.post(f"/v1/admin/users/{u.id}/plan", headers=admin, json={"plan_id": "plus", "reason": "paid via UPI"})
    assert r.status_code == 200 and r.json()["plan_id"] == "plus"
    audit = (await client.get("/v1/admin/audit?action=admin.plan_change", headers=admin)).json()
    assert audit[0]["meta"]["to"] == "plus" and audit[0]["meta"]["reason"] == "paid via UPI"


async def test_sse_requires_auth_and_access(client, auth, make_user, site) -> None:  # noqa: ANN001
    alice, mallory = await make_user(), await make_user()
    wid = await make_watch(alice, simple_spec(site.set("site.test", "/s", "<p>x</p>")))
    assert (await client.get("/v1/stream")).status_code == 401
    assert (await client.get("/v1/stream?ticket=forged.ticket")).status_code == 401
    assert (await client.get(f"/v1/stream?watch={wid}", headers=auth(mallory))).status_code == 404
    t = (await client.post("/v1/stream/ticket", headers=auth(alice))).json()["ticket"]
    from app.core.crypto import verify_payload

    assert verify_payload(t, "sse")["u"] == str(alice.id)
    assert verify_payload(t, "unsub") is None  # purpose-bound: can't be reused as another token type


async def test_hostile_inputs_are_inert(client, auth, make_user, site) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    for q in ["' OR 1=1 --", "%", "_", "\\", "<script>alert(1)</script>", "a" * 100, "ssc') ; DROP TABLE watches; --"]:
        r = await client.get("/v1/explore", params={"q": q})
        assert r.status_code == 200, (q, r.text)
    r = await client.post("/v1/watches", headers=h, json={"title": "<script>alert(1)</script>",
                                                          "spec": simple_spec(site.set("site.test", "/x", "<p>x</p>"))})
    assert r.status_code == 201 and r.json()["title"] == "<script>alert(1)</script>"  # stored as data, escaped on render
    r = await client.post("/v1/intake", headers=h, json={"query": "x" * 1001})
    assert r.status_code == 422
    r = await client.patch("/v1/me/settings", headers=h, json={"display_name": "a" * 81})
    assert r.status_code == 422


async def test_rate_limit_returns_retry_after(client, auth, make_user, respx_mock) -> None:  # noqa: ANN001
    from httpx import Response

    respx_mock.post("https://proj.supabase.co/auth/v1/otp").mock(return_value=Response(200, json={}))
    codes = []
    for _ in range(7):
        r = await client.post("/v1/auth/magic-link", json={"email": "someone@gmail.com"})
        codes.append(r.status_code)
    assert codes[:5] == [200] * 5 and codes[-1] == 429 and "Retry-After" in r.headers
