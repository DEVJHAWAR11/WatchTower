import time
import uuid

import jwt
import respx
from httpx import Response

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import Profile


async def test_health_and_ready(client) -> None:  # noqa: ANN001
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "redis": "ok"}
    token = get_settings().metrics_token.get_secret_value()
    if token:  # a local .env may protect /metrics; both cases must behave
        assert (await client.get("/metrics")).status_code == 401
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    assert (await client.get("/metrics", headers=headers)).status_code == 200


async def test_profile_bootstrap_and_settings(client, auth_kit) -> None:  # noqa: ANN001
    uid = uuid.uuid4()
    h = {"Authorization": f"Bearer {auth_kit.token(uid, 'Asha@Example.com')}"}
    r = await client.get("/v1/me", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "asha@example.com" and body["plan_id"] == "free" and body["timezone"] == "Asia/Kolkata"
    assert body["email_verified"] is True and r.headers["X-Request-ID"]
    r = await client.patch("/v1/me/settings", headers=h, json={
        "handle": "asha_k", "quiet_hours_start": "23:00:00", "quiet_hours_end": "07:00:00", "digest_time": "08:30:00",
        "default_delivery_mode": "digest", "max_alerts_per_hour": 50, "timezone": "Asia/Kolkata"})
    assert r.status_code == 200, r.text
    assert r.json()["handle"] == "asha_k" and r.json()["max_alerts_per_hour"] == 6  # clamped to free plan
    # profile persisted (commit happened before response)
    async with session_scope() as s:
        p = await s.get(Profile, uid)
        assert p.handle == "asha_k" and p.default_delivery_mode == "digest"


async def test_settings_validation(client, auth, make_user) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    for bad in ({"timezone": "Mars/Base"}, {"handle": "Admin"}, {"handle": "a"}, {"default_channels": ["sms"]},
                {"unknown_field": 1}, {"quiet_hours_start": "22:00:00"}):
        r = await client.patch("/v1/me/settings", headers=h, json=bad)
        assert r.status_code in (409, 422), (bad, r.text)
        assert "error" in r.json()
    r = await client.patch("/v1/me/settings", headers=h, json={"default_channels": ["webhook"]})
    assert r.status_code == 403  # free plan has no webhooks


async def test_jwt_attacks_rejected(client, auth_kit) -> None:  # noqa: ANN001
    uid = uuid.uuid4()
    now = int(time.time())
    good = auth_kit.token(uid)
    cases = {
        "none_alg": jwt.encode({"sub": str(uid), "aud": "authenticated", "exp": now + 60}, key="", algorithm="none"),
        "hs256_confusion": jwt.encode({"sub": str(uid), "aud": "authenticated", "iss": "https://proj.supabase.co/auth/v1",
                                       "iat": now, "exp": now + 60}, "anon-key", algorithm="HS256",
                                      headers={"kid": "test-kid"}),
        "expired": auth_kit.token(uid, exp_in=-120),
        "wrong_aud": auth_kit.token(uid, aud="other"),
        "wrong_iss": auth_kit.token(uid, iss="https://evil.supabase.co/auth/v1"),
        "anonymous": auth_kit.token(uid, is_anonymous=True),
        "service_role": auth_kit.token(uid, role="service_role"),
        "tampered": good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB"),
        "garbage": "not.a.jwt",
        "unknown_kid": jwt.encode({"sub": str(uid)}, auth_kit.private_key, algorithm="ES256", headers={"kid": "zzz"}),
    }
    for name, tok in cases.items():
        r = await client.get("/v1/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, (name, r.status_code, r.text)
    assert (await client.get("/v1/me")).status_code == 401
    assert (await client.get("/v1/me", headers={"Authorization": f"Bearer {good}"})).status_code == 200


async def test_admin_role_only_from_app_metadata(client, auth_kit) -> None:  # noqa: ANN001
    uid = uuid.uuid4()
    tok = auth_kit.token(uid, user_metadata={"role": "admin", "email_verified": True})
    assert (await client.get("/v1/admin/system", headers={"Authorization": f"Bearer {tok}"})).status_code == 403
    admin_tok = auth_kit.token(uuid.uuid4(), admin=True)
    r = await client.get("/v1/admin/system", headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 200, r.text
    assert "queues" in r.json()


async def test_suspended_user_blocked(client, auth, make_user) -> None:  # noqa: ANN001
    u = await make_user(status="suspended", status_reason="spam")
    r = await client.get("/v1/me", headers=auth(u))
    assert r.status_code == 403 and "suspended" in r.json()["error"]["message"]


async def test_plans_and_usage(client, auth, make_user) -> None:  # noqa: ANN001
    r = await client.get("/v1/plans")
    plans = {p["id"]: p for p in r.json()}
    assert plans["free"]["price_usd_month"] == 0 and plans["plus"]["price_usd_month"] == 2
    assert plans["pro"]["limits"]["min_interval_seconds"] == 900
    u = await make_user()
    r = await client.get("/v1/me/usage", headers=auth(u))
    assert r.status_code == 200 and r.json()["watches"] == 0 and r.json()["plan"]["id"] == "free"


@respx.mock(assert_all_mocked=False)
async def test_auth_proxy_login_lockout_and_disposable(client, respx_mock) -> None:  # noqa: ANN001
    respx_mock.post("https://proj.supabase.co/auth/v1/token").mock(
        return_value=Response(400, json={"error": "invalid_grant", "error_description": "Invalid login credentials"}))
    for _ in range(8):
        r = await client.post("/v1/auth/login", json={"email": "victim@example.com", "password": "wrong"})
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Invalid email or password"
    r = await client.post("/v1/auth/login", json={"email": "victim@example.com", "password": "wrong"})
    assert r.status_code == 429  # credential-stuffing lockout per account
    r = await client.post("/v1/auth/signup", json={"email": "x@mailinator.com", "password": "Str0ng!pass"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "disposable_email"
    r = await client.post("/v1/auth/signup", json={"email": "x@gmail.com", "password": "password"})
    assert r.status_code == 422
    respx_mock.post("https://proj.supabase.co/auth/v1/signup").mock(
        return_value=Response(200, json={"id": str(uuid.uuid4()), "email": "x@gmail.com"}))
    r = await client.post("/v1/auth/signup", json={"email": "x@gmail.com", "password": "Str0ng!pass",
                                                   "redirect_to": "https://evil.example/cb"})
    assert r.status_code == 422  # open redirect blocked
    r = await client.post("/v1/auth/signup", json={"email": "x@gmail.com", "password": "Str0ng!pass"})
    assert r.status_code == 200 and "Check your inbox" in r.json()["message"]


async def test_error_envelope_and_unknown_route(client) -> None:  # noqa: ANN001
    r = await client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await client.post("/v1/auth/login", content=b"x" * 2_000_000, headers={"content-type": "application/json"})
    assert r.status_code == 413


async def test_dashboard_aggregates_runs_per_watch(client, auth, make_user, site) -> None:  # noqa: ANN001
    from datetime import UTC, datetime, timedelta

    from app.models import Run
    from tests.helpers import make_watch

    u = await make_user()
    wid = await make_watch(u, {"sources": [{"url": site.set("site.test", "/dash", "<p>x</p>")}], "condition": "abc"},
                           title="Dash watch")
    now = datetime.now(UTC)
    async with session_scope() as s:
        s.add(Run(watch_id=wid, status="completed", outcome="skipped_unchanged", started_at=now - timedelta(days=3)))
        s.add(Run(watch_id=wid, status="completed", outcome="error", started_at=now - timedelta(hours=13)))
        s.add(Run(watch_id=wid, status="completed", outcome="matched", llm_called=True, decided_by="llm",
                  started_at=now - timedelta(minutes=5)))
        s.add(Run(watch_id=wid, status="completed", outcome="no_match", started_at=now - timedelta(days=9)))
    r = await client.get("/v1/me/dashboard", headers=auth(u))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["runs_7d"] == 3 and body["totals"]["alerts_7d"] == 1
    assert body["totals"]["ai_skipped_7d"] == 2 and body["totals"]["active_watches"] == 1
    item = body["items"][0]
    assert item["watch"]["title"] == "Dash watch" and item["watch"]["is_owner"] is True
    assert item["last_run"]["outcome"] == "matched" and item["alerts_24h"] == 1
    strip = item["activity"]
    assert len(strip) == 14 and strip[-1] == {"runs": 1, "alerts": 1, "errors": 0}
    assert strip[-2]["errors"] == 1 and sum(b["runs"] for b in strip) == 3
    other = await make_user()
    assert (await client.get("/v1/me/dashboard", headers=auth(other))).json()["items"] == []


async def test_plan_request_is_recorded_for_admins(client, auth, make_user, auth_kit) -> None:  # noqa: ANN001
    u = await make_user()
    h = auth(u)
    assert (await client.post("/v1/me/plan-request", headers=h, json={"plan_id": "free"})).status_code == 409
    assert (await client.post("/v1/me/plan-request", headers=h, json={"plan_id": "gold"})).status_code == 422
    r = await client.post("/v1/me/plan-request", headers=h, json={"plan_id": "plus", "note": "for job hunting"})
    assert r.status_code == 202, r.text
    admin = {"Authorization": f"Bearer {auth_kit.token(uuid.uuid4(), admin=True)}"}
    rows = (await client.get("/v1/admin/audit", headers=admin, params={"action": "plan.request"})).json()
    assert rows[0]["meta"]["plan_id"] == "plus" and rows[0]["actor_id"] == str(u.id)
    state = await client.get("/v1/me/dashboard", headers=h)
    assert state.status_code == 200
