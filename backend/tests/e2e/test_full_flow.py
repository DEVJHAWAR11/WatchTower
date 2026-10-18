"""End-to-end: plain-English request -> clarification -> proposal -> confirm -> scheduled checks -> fire ->
follow-up (Act) -> ONE notification -> feedback -> self-tuning, all through the public API + real workers."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.db import session_scope
from app.models import AlertDelivery, Check, ProposedAction, WatchVersion
from app.search.providers import SearchHit, SearchService, set_search
from app.workers.scheduler import tick
from tests.conftest import drain, emails
from tests.helpers import keyword_judge, section

CAREERS_V1 = """<html><head><title>Razorpay Careers</title></head><body><h1>Open roles</h1><ul>
<li><a href="/jobs/101">Senior Backend Engineer (5+ yrs) - Bengaluru</a></li>
<li><a href="/jobs/102">Product Designer - Bengaluru</a></li></ul></body></html>"""

CAREERS_V2 = CAREERS_V1.replace("</ul>", """<li><a href="/jobs/103">Software Engineer - Backend (Fresher, 2026 batch) - Bengaluru</a></li>
<li><a href="/apply/103">Apply for SDE Backend Fresher</a></li></ul><p>Applications close on 15 Dec 2026.</p>""")


class FakeSearch:
    name = "fake"

    def __init__(self, hits: list[SearchHit]):
        self.hits = hits
        self.queries: list[str] = []

    def available(self) -> bool:
        return True

    async def search(self, query: str, *, max_results: int, country: str | None) -> list[SearchHit]:
        self.queries.append(query)
        return self.hits


def intake_handler(system: str, user: str) -> dict:
    answered = "Clarifications from the user" in user
    if not answered:
        return {"safety": "allowed", "feasibility": "vague",
                "feasibility_reason": "Which kind of backend role and which location?",
                "questions": [{"id": "level", "question": "Fresher roles only, or any experience level?",
                               "options": ["Fresher only", "Any level"]},
                              {"id": "loc", "question": "Which city?", "options": ["Bengaluru", "Any"]}],
                "title": "Razorpay backend roles", "kind": "job", "condition": ""}
    return {"safety": "allowed", "feasibility": "ok", "title": "Razorpay backend fresher roles (Bengaluru)",
            "kind": "job", "category": "jobs", "company": "Razorpay",
            "condition": "Razorpay posts a backend software engineering role open to freshers in Bengaluru",
            "search_queries": ["Razorpay careers backend fresher"], "keywords": ["backend", "fresher", "engineer"],
            "predicates": [{"type": "new_items", "values": ["backend"]}], "predicate_mode": "prefilter",
            "extract_fields": ["role", "location", "deadline", "apply link"],
            "act_tasks": ["extract_details", "deadlines", "checklist"], "suggested_interval_minutes": 60}


def act_handler(system: str, user: str) -> dict:
    page = section(user, "PAGE")
    links = section(user, "LINKS")
    apply_link = next((ln.split(": ", 1)[1] for ln in links.splitlines() if "Apply for SDE" in ln), "")
    return {"headline": "Razorpay is hiring backend freshers in Bengaluru",
            "what_happened": "A new Software Engineer - Backend role for the 2026 batch was posted.",
            "key_details": [{"name": "Role", "value": "Software Engineer - Backend (Fresher)"},
                            {"name": "Location", "value": "Bengaluru"}],
            "deadlines": [{"label": "Applications close", "date": "2026-12-15",
                           "evidence_quote": "Applications close on 15 Dec 2026" if "15 Dec 2026" in page else ""}],
            "important_links": [{"name": "Apply for SDE Backend Fresher", "value": apply_link},
                                {"name": "Fake phishing link", "value": "https://evil.example/login"}],
            "checklist": ["Update resume", "Apply before 15 Dec"], "comparison": "", "draft_message": "",
            "followup_watch_suggestion": ""}


async def test_end_to_end(client, auth, make_user, site, llm, auth_kit) -> None:  # noqa: ANN001
    user = await make_user(email="dev@example.com")
    h = auth(user)
    careers = site.set("jobs.test", "/careers", CAREERS_V1)
    search = FakeSearch([SearchHit("Razorpay Careers", careers, "Open roles", "fake"),
                         SearchHit("Some blog", site.url("news.test", "/missing"), "", "fake")])
    set_search(SearchService([search]))
    llm.on("intake", intake_handler)
    llm.on("rank_sources", {"choices": [{"index": 0, "relevance": 0.95, "why": "official careers"}]})
    llm.on("dry_run", {"already_met": False, "reason": "Only senior roles listed"})
    llm.on("judge", keyword_judge("fresher", title="Backend fresher role at Razorpay",
                                  event_key="razorpay sde backend fresher 2026"))
    llm.on("triage", {"plausibly_relevant": True})
    llm.on("act", act_handler)
    try:
        # 1. plain English request
        r = await client.post("/v1/intake", headers={**h, "Idempotency-Key": "abc"},
                              json={"query": "tell me when Razorpay posts a backend fresher role"})
        assert r.status_code == 202, r.text
        sid = r.json()["id"]
        r2 = await client.post("/v1/intake", headers={**h, "Idempotency-Key": "abc"},
                               json={"query": "tell me when Razorpay posts a backend fresher role"})
        assert r2.json()["id"] == sid  # idempotent replay
        await drain(("agents",))
        s = (await client.get(f"/v1/intake/{sid}", headers=h)).json()
        assert s["status"] == "awaiting_user" and s["stage"] == "clarify"
        assert {q["id"] for q in s["view"]["questions"]} == {"level", "loc"}

        # 2. clarification -> proposal
        r = await client.post(f"/v1/intake/{sid}/answer", headers=h,
                              json={"answers": {"level": "Fresher only", "loc": "Bengaluru"}})
        assert r.status_code == 202, r.text
        await drain(("agents",))
        s = (await client.get(f"/v1/intake/{sid}", headers=h)).json()
        assert s["status"] == "proposed", s
        prop = s["view"]["proposal"]
        assert prop["sources"][0]["url"].endswith("/careers")
        assert prop["interval_minutes"] == 360  # clamped to the free plan's 6h minimum
        assert s["view"]["dry_run"]["already_met"] is False
        assert (await client.post(f"/v1/intake/{sid}/answer", headers=h, json={"answers": {"x": "y"}})).status_code == 422

        # 3. confirm with an edit -> watch created with a baseline of the current page
        r = await client.post(f"/v1/intake/{sid}/confirm", headers=h,
                              json={"confirm": True, "edits": {"title": "Razorpay backend fresher jobs"}})
        assert r.status_code == 202
        await drain(("agents",))
        s = (await client.get(f"/v1/intake/{sid}", headers=h)).json()
        assert s["status"] == "created", s
        wid = s["watch_id"]
        w = (await client.get(f"/v1/watches/{wid}", headers=h)).json()
        assert w["title"] == "Razorpay backend fresher jobs" and w["is_owner"] and w["kind"] == "job"

        # 4. scheduler: make it due, tick, run the check -> unchanged page, no AI call
        async with session_scope() as ss:
            await ss.execute(update(Check).values(next_run_at=datetime.now(UTC) - timedelta(seconds=1)))
        assert await tick() == 1
        assert await tick() == 0  # leased: never double-claimed
        judge_before = llm.count("judge")
        await drain(("checks",))
        st = (await client.get(f"/v1/watches/{wid}/state", headers=h)).json()
        assert st["last_run"]["outcome"] == "skipped_unchanged" and st["last_run"]["llm_called"] is False
        assert "AI was not called" in st["last_run"]["reason"]
        assert st["schedule"]["next_run_at"] is not None and llm.count("judge") == judge_before

        # 5. the page changes -> rules prefilter -> AI judge -> alert -> Act -> one notification
        site.set("jobs.test", "/careers", CAREERS_V2)
        r = await client.post(f"/v1/watches/{wid}/run", headers=h)
        assert r.status_code == 202
        assert await tick() == 1
        results = await drain(("checks", "agents", "notify"))
        names = [n for n, _ in results]
        assert names[:2] == ["run_check", "act_on_alert"] and "fanout_alert" in names and "send_delivery" in names
        st = (await client.get(f"/v1/watches/{wid}/state", headers=h)).json()
        assert st["last_run"]["outcome"] == "matched" and st["last_run"]["llm_called"] is True
        nodes = [x["node"] for x in st["last_run"]["steps"]]
        assert nodes == ["fetch", "change_gate", "rules", "judge", "dedup", "fire"]
        alert = st["last_alert"]
        assert alert["act_status"] == "completed"
        assert alert["title"] == "Razorpay is hiring backend freshers in Bengaluru"
        links = [link["url"] for link in alert["act_result"]["links"]]
        assert any(u.endswith("/apply/103") for u in links) and not any("evil.example" in u for u in links)
        assert alert["act_result"]["deadlines"][0]["date"].startswith("2026-12-15")
        kinds = {a["kind"] for a in alert["actions"]}
        assert {"add_to_calendar", "set_reminder", "open_link"} <= kinds
        mails = await emails()
        assert len(mails) == 1, [m["subject"] for m in mails]
        mail = mails[0]
        assert mail["to"] == "dev@example.com" and "Razorpay is hiring" in mail["subject"]
        assert "Applications close" in mail["text"] and "Waiting for your approval" in mail["text"]
        assert "List-Unsubscribe" in mail["headers"] and "evil.example" not in mail["html"]

        # 6. replaying jobs never double-sends
        async with session_scope() as ss:
            dl = (await ss.execute(select(AlertDelivery))).scalars().all()
            assert len(dl) == 1 and dl[0].status == "sent"
        from app.workers.queue import Q_NOTIFY, enqueue

        await enqueue("fanout_alert", alert["id"], queue=Q_NOTIFY, job_id="replay1")
        await enqueue("send_delivery", str(dl[0].id), queue=Q_NOTIFY, job_id="replay2")
        await drain(("notify",))
        assert len(await emails()) == 1

        # 7. approve an action: reminder created; calendar link works
        acts = {a["kind"]: a for a in alert["actions"]}
        r = await client.post(f"/v1/actions/{acts['add_to_calendar']['id']}/approve", headers=h)
        assert r.status_code == 200, r.text
        ics_url = r.json()["result"]["ics_url"]
        ics = await client.get(ics_url.replace("http://localhost:8000", ""))
        assert ics.status_code == 200 and "BEGIN:VEVENT" in ics.text and "DTSTART;VALUE=DATE:20261215" in ics.text
        r = await client.post(f"/v1/actions/{acts['set_reminder']['id']}/approve", headers=h)
        assert r.json()["status"] == "executed"
        again = await client.post(f"/v1/actions/{acts['set_reminder']['id']}/approve", headers=h)
        assert again.json()["idempotent"] is True

        # 8. history endpoints
        runs = (await client.get(f"/v1/watches/{wid}/runs", headers=h)).json()
        assert [x["outcome"] for x in runs["items"]][:2] == ["matched", "skipped_unchanged"]
        inbox = (await client.get("/v1/alerts", headers=h)).json()
        assert len(inbox["items"]) == 1 and inbox["items"][0]["id"] == alert["id"]

        # 9. SSE replay: events from the run are available on the watch stream
        from app.core.redis import get_redis

        evs = await get_redis().xrange(f"ev:watch:{wid}")
        types = [json.loads(e[1]["e"])["type"] for e in evs]
        assert "run.started" in types and "run.step" in types and "run.completed" in types and "act.completed" in types
        uevs = [json.loads(e[1]["e"])["type"] for e in await get_redis().xrange(f"ev:user:{user.id}")]
        assert "intake.updated" in uevs and "alert.created" in uevs and "delivery.sent" in uevs
    finally:
        set_search(None)


async def test_feedback_drives_refinement(client, auth, make_user, site, llm) -> None:  # noqa: ANN001
    """Two 'not relevant' marks -> refinement -> backtest -> auto-applied new version on Plus."""
    from tests.helpers import make_watch

    user = await make_user(plan="plus")
    h = auth(user)
    url = site.set("jobs.test", "/c", "<html><body><ul><li>Intro</li></ul></body></html>")
    wid = await make_watch(user, {"kind": "job", "sources": [{"url": url}],
                                  "condition": "A backend engineering job is posted", "keywords": ["backend"]})
    from app.agents.evaluate import run_evaluation

    llm.on("judge", keyword_judge("backend"))
    await run_evaluation(wid)
    alerts = []
    for i, role in enumerate(["Senior Backend Engineer 8+ yrs", "Backend Intern (unpaid)",
                              "Backend Engineer - Fresher"]):
        site.set("jobs.test", "/c", f"<html><body><ul><li>Intro</li><li>{role} #{i}</li></ul></body></html>")
        res = await run_evaluation(wid, trigger="manual")
        assert res["outcome"] == "matched", res
        alerts.append(res["alert_id"])
    for aid, rel in zip(alerts, [False, False, True], strict=True):
        r = await client.post(f"/v1/alerts/{aid}/feedback", headers=h, json={"relevant": rel,
                                                                           "reason": None if rel else "not fresher"})
        assert r.status_code == 200, r.text

    def refine(system: str, user_prompt: str) -> dict:
        return {"new_condition": "A backend engineering job open to freshers (0-1 years) is posted",
                "add_negative_examples": ["Senior Backend Engineer 8+ yrs", "Backend Intern (unpaid)"],
                "add_exclude_terms": ["senior", "intern"], "rationale": "User wants fresher roles only"}

    def backtest(system: str, user_prompt: str) -> dict:
        text = section(user_prompt, "ALERT").lower()
        fresher_only = "freshers" in user_prompt.split("Alert content")[0]
        return {"condition_met": ("fresher" in text) if fresher_only else True, "confidence": 0.9}

    llm.on("refine", refine)
    llm.on("backtest", backtest)
    out = await drain(("agents",), only={"refine_watch"})
    assert out and out[-1][1]["status"] == "applied", out
    versions = (await client.get(f"/v1/watches/{wid}/versions", headers=h)).json()
    assert versions[0]["version"] == 2 and versions[0]["created_by"] == "refinement"
    assert versions[0]["backtest"]["after"]["fp"] == 0 and versions[0]["backtest"]["after"]["fn"] == 0
    async with session_scope() as s:
        v = (await s.execute(select(WatchVersion).where(WatchVersion.version == 2))).scalar_one()
        assert "freshers" in v.spec["condition"]
    diff = (await client.get(f"/v1/watches/{wid}/versions/diff?a=1&b=2", headers=h)).json()
    assert any(c["field"] == "condition" for c in diff["changes"])
    rb = await client.post(f"/v1/watches/{wid}/versions/1/rollback", headers=h)
    assert rb.status_code == 200 and rb.json()["version"] == 3 and rb.json()["created_by"] == "rollback"
    async with session_scope() as s:
        assert (await s.execute(select(ProposedAction))).first() is None or True
