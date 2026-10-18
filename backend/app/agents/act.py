"""Act graph: after a watch fires, do the follow-up work BEFORE notifying, then hand over to fan-out.

    gather -> analyze (LLM) -> validate (links/dates must be grounded) -> propose_actions -> finalize

Nothing here executes side effects on the user's behalf: actions are proposals that need approval.
The whole graph runs under a timeout; on timeout/failure the alert is still sent (without the extras).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents import prompts
from app.agents.schemas import ActOut
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import QuotaExceeded
from app.core.logging import get_logger
from app.llm.client import LLMError, get_llm
from app.llm.safety import quote_in_text, scan_and_strip
from app.models import Alert, Profile, ProposedAction, Watch, WatchSourceState, WatchVersion
from app.observability.metrics import AGENT_NODE_SECONDS
from app.realtime.events import publish_watch
from app.schemas.spec import WatchSpec
from app.services.plans import consume, effective_plan_id, get_plan
from app.workers.queue import Q_NOTIFY, enqueue

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
APPLY_WORDS = ("apply", "register", "registration", "application", "notification", "admit", "result", "download",
               "buy", "official", "pdf", "login", "form")
FOLLOWUP_KINDS = {"exam_notification", "exam_result", "admission", "scholarship", "job", "ipo", "event"}


class ActState(TypedDict, total=False):
    alert_id: str
    watch_id: str
    owner_id: str
    plan_id: str
    token_limit: int | None
    spec: dict[str, Any]
    kind: str
    alert: dict[str, Any]
    context: str
    links: list[dict[str, str]]
    previous: str
    out: dict[str, Any]
    result: dict[str, Any]
    actions: list[dict[str, Any]]
    status: str
    note: str


def _timed(node: str):  # noqa: ANN202
    def deco(fn):  # noqa: ANN001, ANN202
        async def wrapper(state: ActState) -> dict[str, Any]:
            t0 = time.monotonic()
            try:
                return await fn(state)
            finally:
                AGENT_NODE_SECONDS.labels(graph="act", node=node).observe(time.monotonic() - t0)
        return wrapper
    return deco


@_timed("analyze")
async def node_analyze(state: ActState) -> dict[str, Any]:
    spec = WatchSpec.model_validate(state["spec"])
    a = state["alert"]
    ctx = scan_and_strip(state["context"]).cleaned_text
    links = "\n".join(f"- {link['text'][:80]}: {link['href']}" for link in state["links"][:80])
    facts = "; ".join(f"{k}: {v}" for k, v in (a.get("key_facts") or {}).items())
    tasks = list(spec.act.tasks)
    if spec.extract_fields:
        tasks.append("extract: " + ", ".join(spec.extract_fields))
    try:
        res = await get_llm().structured(
            purpose="act", tier="smart", system=prompts.ACT_SYSTEM,
            user=prompts.act_user(condition=spec.condition, now=prompts.now_ist_str(), alert_title=a["title"],
                                  alert_summary=a["summary"], facts=facts, tasks=tasks,
                                  instructions=spec.act.instructions, context=ctx, links=links,
                                  previous=state.get("previous", "")),
            schema=ActOut, user_id=uuid.UUID(state["owner_id"]), plan_id=state["plan_id"],
            token_limit_per_day=state.get("token_limit"), max_tokens=1600,
        )
    except LLMError as e:
        return {"status": "failed", "note": f"follow-up AI unavailable: {e.code}"}
    return {"out": res.data.model_dump()}


def _parse_date(raw: str) -> datetime | None:
    try:
        dt = dateparser.parse(raw, dayfirst=True, fuzzy=False)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt


@_timed("validate")
async def node_validate(state: ActState) -> dict[str, Any]:
    out = ActOut.model_validate(state["out"])
    allowed_links = {link["href"] for link in state["links"]} | {state["alert"]["source_url"]}
    allowed_hosts = {urlsplit(u).hostname for u in allowed_links}
    links = []
    for kf in out.important_links:
        url = kf.value.strip()
        # grounded: exact link from the page, or same host as a page link (relative/canonical variants)
        if url.startswith(("http://", "https://")) and (url in allowed_links or urlsplit(url).hostname in allowed_hosts):
            links.append({"name": kf.name[:80], "url": url[:2048]})
    now = datetime.now(UTC)
    deadlines = []
    for d in out.deadlines:
        dt = _parse_date(d.date)
        if dt is None or dt < now - timedelta(days=1) or dt > now + timedelta(days=730):
            continue
        if not d.evidence_quote or not quote_in_text(d.evidence_quote, state["context"], min_len=6):
            continue  # never surface a date we can't ground in the page
        deadlines.append({"label": d.label[:120], "date": dt.isoformat(), "evidence": d.evidence_quote[:300]})
    result = {
        "headline": out.headline, "what_happened": out.what_happened, "key_details": out.details_dict(),
        "deadlines": sorted(deadlines, key=lambda x: x["date"]), "links": links,
        "comparison": out.comparison, "checklist": out.checklist, "draft_message": out.draft_message,
        "followup": out.followup_watch_suggestion,
    }
    return {"result": result}


@_timed("propose")
async def node_propose(state: ActState) -> dict[str, Any]:
    r = state["result"]
    now = datetime.now(UTC)
    actions: list[dict[str, Any]] = []
    for d in r["deadlines"][:3]:
        when = datetime.fromisoformat(d["date"])
        actions.append({"kind": "add_to_calendar", "title": f"Add '{d['label']}' to calendar",
                        "payload": {"title": f"{d['label']} - {state['alert']['title']}"[:200], "start": d["date"],
                                    "url": state["alert"]["source_url"]}, "expires_at": when})
        lead = timedelta(days=1) if when - now > timedelta(days=2) else timedelta(hours=2)
        remind_at = max(now + timedelta(minutes=5), when - lead)
        if remind_at < when:
            actions.append({"kind": "set_reminder", "title": f"Remind me before: {d['label']}",
                            "payload": {"remind_at": remind_at.isoformat(),
                                        "message": f"{d['label']} is due {when.astimezone(IST):%d %b, %I:%M %p}. "
                                                   f"({state['alert']['title']})"[:500]},
                            "expires_at": when})
    for link in r["links"]:
        if any(w in link["name"].lower() for w in APPLY_WORDS):
            actions.append({"kind": "open_link", "title": f"Open: {link['name']}"[:200], "payload": {"url": link["url"]},
                            "expires_at": now + timedelta(days=30)})
            break
    if r.get("draft_message"):
        actions.append({"kind": "draft_email", "title": "Email me this draft", "expires_at": now + timedelta(days=30),
                        "payload": {"subject": f"Draft: {state['alert']['title']}"[:150], "body": r["draft_message"]}})
    if r.get("followup") and state["kind"] in FOLLOWUP_KINDS:
        actions.append({"kind": "create_followup_watch", "title": f"Start a watch: {r['followup']}"[:200],
                        "payload": {"query": r["followup"][:300]}, "expires_at": now + timedelta(days=60)})
    price = (state["alert"].get("key_facts") or {}).get("price")
    if state["kind"] == "price_drop" and price:
        try:
            p = float(str(price).replace(",", ""))
            actions.append({"kind": "adjust_threshold", "title": f"Only alert me below ₹{p * 0.95:,.0f} next time",
                            "payload": {"threshold": round(p * 0.95, 2)}, "owner_only": True,
                            "expires_at": now + timedelta(days=30)})
        except ValueError:
            pass
    return {"actions": actions, "status": "completed"}


def _route_after_analyze(state: ActState) -> str:
    return END if state.get("status") == "failed" else "validate"


def build_act_graph() -> Any:
    g = StateGraph(ActState)
    g.add_node("analyze", node_analyze)
    g.add_node("validate", node_validate)
    g.add_node("propose", node_propose)
    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", _route_after_analyze, ["validate", END])
    g.add_edge("validate", "propose")
    g.add_edge("propose", END)
    return g.compile()


_graph: Any = None


def act_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_act_graph()
    return _graph


async def _gather(alert_id: uuid.UUID) -> ActState | str:
    async with session_scope() as s:
        alert = await s.get(Alert, alert_id, with_for_update=True)
        if alert is None:
            return "missing"
        if alert.act_status != "pending":
            return alert.act_status
        w = await s.get(Watch, alert.watch_id)
        ver = await s.get(WatchVersion, alert.version_id or w.current_version_id)
        owner = await s.get(Profile, w.owner_id)
        spec = WatchSpec.model_validate(ver.spec)
        if not spec.act.enabled:
            alert.act_status = "skipped"
            return "skipped"
        plan = await get_plan(s, effective_plan_id(owner))
        community = w.visibility == "public" and w.subscriber_count >= 10
        if not community:
            try:
                await consume(s, owner.id, "acts", "month", plan.limit("acts_per_month"))
            except QuotaExceeded:
                alert.act_status = "skipped"
                alert.act_result = {"note": "Monthly follow-up limit reached for this plan."}
                return "skipped"
        state_rows = (await s.execute(select(WatchSourceState).where(WatchSourceState.watch_id == w.id))).scalars().all()
        links: list[dict[str, str]] = []
        page_text = ""
        for row in state_rows:
            links.extend(row.items or [])
            page_text += "\n" + (row.view_text or "")
        context = (alert.context_excerpt or "")
        if alert.evidence and page_text:
            idx = page_text.lower().find(alert.evidence.lower()[:40])
            if idx >= 0:
                context += "\n…\n" + page_text[max(0, idx - 2500): idx + 3500]
        if len(context) < 2000:
            context += "\n" + page_text[:6000]
        prev = (await s.execute(
            select(Alert.title, Alert.summary, Alert.created_at).where(Alert.watch_id == w.id, Alert.id != alert.id)
            .order_by(Alert.created_at.desc()).limit(3)
        )).all()
        previous = "\n".join(f"{p.created_at:%d %b %Y}: {p.title} - {p.summary[:200]}" for p in prev)
        return ActState(
            alert_id=str(alert.id), watch_id=str(w.id), owner_id=str(owner.id),
            plan_id="pro" if community else plan.id,
            token_limit=None if community else plan.limit("llm_tokens_per_day"), spec=ver.spec, kind=spec.kind,
            alert={"title": alert.title, "summary": alert.summary, "key_facts": alert.key_facts or {},
                   "source_url": alert.source_url, "evidence": alert.evidence},
            context=context[:12000], links=links[:300], previous=previous,
        )


async def act_on_alert(ctx: dict[str, Any] | None, alert_id: str) -> dict[str, Any]:
    aid = uuid.UUID(alert_id)
    gathered = await _gather(aid)
    if isinstance(gathered, str):
        if gathered in ("skipped", "completed", "failed", "timeout"):
            await enqueue("fanout_alert", alert_id, queue=Q_NOTIFY, job_id=f"fanout:{alert_id}")
        return {"status": gathered}
    state = gathered
    await publish_watch(state["watch_id"], "act.started", {"alert_id": alert_id})
    status, note, result, actions = "failed", "", {}, []
    try:
        async with asyncio.timeout(get_settings().act_timeout_seconds):
            final = await act_graph().ainvoke(state)
        status = final.get("status", "failed")
        note = final.get("note", "")
        result = final.get("result") or {}
        actions = final.get("actions") or []
    except TimeoutError:
        status, note = "timeout", "follow-up took too long"
    except Exception as e:
        log.exception("act_crashed", alert_id=alert_id)
        status, note = "failed", f"internal error ({type(e).__name__})"
    async with session_scope() as s:
        alert = await s.get(Alert, aid, with_for_update=True)
        if alert is None:
            return {"status": "missing"}
        alert.act_status = status
        alert.act_result = {**result, **({"note": note} if note else {})}
        if result.get("headline"):
            alert.title = result["headline"][:200]
        for a in actions:
            s.add(ProposedAction(alert_id=aid, kind=a["kind"], title=a["title"][:200], payload=a["payload"],
                                 owner_only=bool(a.get("owner_only")), expires_at=a.get("expires_at")))
    await publish_watch(state["watch_id"], "act.completed", {"alert_id": alert_id, "status": status,
                                                             "actions": len(actions)})
    await enqueue("fanout_alert", alert_id, queue=Q_NOTIFY, job_id=f"fanout:{alert_id}")
    return {"status": status, "actions": len(actions)}
