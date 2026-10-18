"""Intake graph: plain-language request -> validated, tested watch (with human-in-the-loop interrupts).

    screen -> analyze --(refuse/reject)--> END
                 |--(vague)--> clarify [interrupt: questions] --> analyze
                 v
              discover -> validate --(no usable page)--> need_url [interrupt] --> validate
                 v
              compile -> dry_run -> propose [interrupt: confirm/edit] --> create -> END

State is checkpointed in Postgres (thread_id = intake session id) so a user can answer hours later.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from dateutil import parser as dateparser
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError
from sqlalchemy import func, select, text

from app.agents import prompts
from app.agents.predicates import ViewContext, eval_all
from app.agents.schemas import DryRunOut, IntakeAnalysis, SourceRanking
from app.core.db import session_scope
from app.core.logging import get_logger
from app.fetch.normalize import content_hash
from app.fetch.service import SourceUnavailable, fetch_source
from app.fetch.ssrf import SSRFBlocked, validate_url
from app.fetch.urls import canonicalize_url
from app.llm.client import LLMError, get_llm
from app.llm.safety import quote_in_text, scan_and_strip
from app.models import IntakeSession, Profile, WatchSourceState
from app.realtime.events import publish_user
from app.schemas.spec import Predicate, WatchSpec
from app.search.providers import SearchError, get_search
from app.search.registry import ats_candidates, github_release_feed, match_registry
from app.services.plans import clamp_interval, effective_plan_id, get_plan

log = get_logger(__name__)

MAX_ROUNDS = 2
MAX_CANDIDATES = 8
URL_RE = re.compile(r"https?://[^\s<>\"'()]+", re.I)
CATEGORY_BY_KIND = {
    "job": "jobs", "exam_result": "exams-results", "exam_notification": "exams-results", "admission": "admissions",
    "scholarship": "scholarships", "ipo": "ipo", "price_drop": "price-drops", "restock": "restocks",
    "release": "tech-releases", "news": "news", "event": "events", "generic": "other",
}

# Cheap deterministic screens that run before any LLM call.
# A private person referenced possessively. `ex(?![-\w])` so "ex-showroom" is not "my ex".
_PERSON = (r"(?:my|her|his|their)\s+(?:ex(?![-\w])|girlfriend|boyfriend|gf|bf|wife|husband|crush|neighbou?r|"
           r"colleague|boss|classmate|roommate|brother'?s\s+girlfriend|sister'?s\s+boyfriend|friend)")
_HARM_PATTERNS = [
    (re.compile(r"\b(track|monitor|watch|spy|stalk|follow)\b.{0,40}\b" + _PERSON, re.I), "stalking_private_person"),
    (re.compile(r"\b" + _PERSON + r"\b.{0,40}\b(leaves?|left|comes?\s+home|goes\s+out|is\s+(?:at|home|out|online)|"
                r"location|whereabouts|posts?|online|last\s+seen|texts?|messages?)\b", re.I), "stalking_private_person"),
    (re.compile(r"\b(live\s+location|whereabouts|home\s+address|phone\s+number|mobile\s+number)\s+of\b", re.I),
     "doxxing"),
    (re.compile(r"\b(last\s+seen|online\s+status|goes\s+online|is\s+online)\b.{0,40}\b(whatsapp|instagram|insta|"
                r"snapchat|telegram|facebook)\b", re.I), "stalking_private_person"),
    (re.compile(r"\b(hack|hacking|ddos|brute.?force|crack)\b.{0,40}\b(account|password|site|website|portal|server|"
                r"wifi|database|phone)\b", re.I), "malware_or_hacking"),
    (re.compile(r"\bbypass\s+(the\s+)?(captcha|login|paywall|otp)\b", re.I), "malware_or_hacking"),
    (re.compile(r"\b(leaked|dump(ed)?|stolen)\s+(database|data|nudes|photos|credit\s+card|card)s?\b", re.I), "illegal"),
]


class IntakeState(TypedDict, total=False):
    session_id: str
    user_id: str
    plan_id: str
    token_limit: int | None
    max_sources: int
    min_interval: int
    query: str
    urls: list[str]
    answers: list[list[str]]
    rounds: int
    analysis: dict[str, Any]
    candidates: list[dict[str, Any]]
    validated: list[dict[str, Any]]
    chosen: list[dict[str, Any]]
    url_asks: int
    similar: list[dict[str, Any]]
    spec: dict[str, Any]
    dry_run: dict[str, Any]
    status: str
    message: str
    watch_id: str | None
    edits: dict[str, Any]


# ------------------------------------------------------------------ helpers
async def _update_session(state: IntakeState, status: str, stage: str, view: dict[str, Any]) -> None:
    sid = uuid.UUID(state["session_id"])
    async with session_scope() as s:
        row = await s.get(IntakeSession, sid)
        if row is None:
            return
        row.status = status
        row.stage = stage
        row.view = view
        row.rounds = int(state.get("rounds", 0))
        if state.get("watch_id"):
            row.watch_id = uuid.UUID(state["watch_id"])
    await publish_user(state["user_id"], "intake.updated", {"session_id": state["session_id"], "status": status,
                                                            "stage": stage, "view": view})


def _llm_kwargs(state: IntakeState) -> dict[str, Any]:
    return {"user_id": uuid.UUID(state["user_id"]), "plan_id": state["plan_id"],
            "token_limit_per_day": state.get("token_limit")}


def extract_urls(text_: str) -> list[str]:
    out: list[str] = []
    for m in URL_RE.findall(text_):
        u = m.rstrip(".,;:!?)")
        try:
            validate_url(u)
            out.append(canonicalize_url(u))
        except (SSRFBlocked, ValueError):
            continue
    return list(dict.fromkeys(out))[:5]


def pre_screen(query: str) -> tuple[str, str] | None:
    """Returns (status, message) if the request can be rejected without an LLM."""
    q = query.strip()
    if len(q) < 4 or not re.search(r"[A-Za-zऀ-ॿ]{2,}", q):
        return "rejected", "Tell me what you'd like to keep an eye on, e.g. 'Alert me when SSC CGL 2026 results are out'."
    for rx, cat in _HARM_PATTERNS:
        if rx.search(q):
            return "refused", _refusal_message(cat)
    return None


def _refusal_message(category: str) -> str:
    return {
        "stalking_private_person": "I can't help monitor a private person's activity or whereabouts. I can watch public "
                                   "pages like job boards, exam results, prices or official announcements.",
        "doxxing": "I can't help find or track someone's personal details.",
        "malware_or_hacking": "I can't help with getting around security or accessing systems without permission.",
        "illegal": "I can't help with that request.",
        "harassment": "I can't help with that request.",
        "adult": "Watchtower doesn't monitor adult content.",
        "spam_or_abuse": "That looks like it would abuse a website or other people, so I can't set it up.",
    }.get(category, "I can't help with that request.")


# ------------------------------------------------------------------ nodes
async def node_analyze(state: IntakeState) -> dict[str, Any]:
    await _update_session(state, "running", "understanding", {"message": "Understanding your request…"})
    screened = pre_screen(state["query"])
    if screened:
        status, msg = screened
        view = {"message": msg, "reason_code": "pre_screen"}
        await _update_session(state, status, "done", view)
        return {"status": status, "message": msg}
    answers = [(a[0], a[1]) for a in state.get("answers", [])]
    try:
        res = await get_llm().structured(
            purpose="intake", tier="smart", system=prompts.INTAKE_SYSTEM,
            user=prompts.intake_user(state["query"], answers, state.get("urls", []), prompts.today_ist()),
            schema=IntakeAnalysis, max_tokens=1800, **_llm_kwargs(state),
        )
    except LLMError as e:
        msg = ("Our AI is busy right now. Please try again in a few minutes."
               if e.code != "user_budget" else "You've reached today's AI usage limit for your plan.")
        await _update_session(state, "failed", "done", {"message": msg, "reason_code": e.code})
        return {"status": "failed", "message": msg}
    a = res.data
    upd: dict[str, Any] = {"analysis": a.model_dump()}
    if a.safety == "refuse":
        msg = _refusal_message(a.safety_category)
        await _update_session(state, "refused", "done", {"message": msg, "reason_code": a.safety_category})
        return {**upd, "status": "refused", "message": msg}
    hard_reject = {"impossible", "contradictory", "past_event", "not_web_observable", "needs_login"}
    if a.feasibility in hard_reject:
        msg = a.feasibility_reason or "This can't be watched on the public web."
        view = {"message": msg, "reason_code": a.feasibility, "alternatives": a.alternatives}
        await _update_session(state, "rejected", "done", view)
        return {**upd, "status": "rejected", "message": msg}
    if a.feasibility in ("vague", "too_broad"):
        if a.questions and int(state.get("rounds", 0)) < MAX_ROUNDS:
            return {**upd, "status": "clarify"}
        if not a.condition or a.feasibility == "too_broad":
            msg = ("I still can't tell exactly what to watch. Try naming the site, exam, company or product."
                   + (f" ({a.feasibility_reason})" if a.feasibility_reason else ""))
            await _update_session(state, "rejected", "done", {"message": msg, "reason_code": a.feasibility,
                                                              "alternatives": a.alternatives})
            return {**upd, "status": "rejected", "message": msg}
    if not a.condition:
        return {**upd, "status": "clarify"} if int(state.get("rounds", 0)) < MAX_ROUNDS else {
            **upd, "status": "rejected", "message": "Couldn't understand the request."}
    return {**upd, "status": "ok"}


async def node_clarify(state: IntakeState) -> dict[str, Any]:
    a = IntakeAnalysis.model_validate(state["analysis"])
    questions = [q.model_dump() for q in a.questions[:3]] or [
        {"id": "detail", "question": "Could you be more specific about what should trigger the alert?", "options": []}]
    view = {"message": a.feasibility_reason or "A couple of quick questions so I watch the right thing:",
            "questions": questions}
    await _update_session(state, "awaiting_user", "clarify", view)
    reply = interrupt({"type": "questions", "questions": questions})
    answers = list(state.get("answers", []))
    given = reply.get("answers", {}) if isinstance(reply, dict) else {}
    for q in questions:
        ans = str(given.get(q["id"], "")).strip()[:300]
        if ans:
            answers.append([q["question"], ans])
    extra_urls = extract_urls(" ".join(str(v) for v in given.values()))
    return {"answers": answers, "rounds": int(state.get("rounds", 0)) + 1,
            "urls": list(dict.fromkeys(state.get("urls", []) + extra_urls))}


async def node_discover(state: IntakeState) -> dict[str, Any]:
    a = IntakeAnalysis.model_validate(state["analysis"])
    await _update_session(state, "running", "searching", {"message": "Finding the best pages to watch…",
                                                          "title": a.title, "condition": a.condition})
    cands: list[dict[str, Any]] = []
    for u in state.get("urls", []):
        cands.append({"url": u, "title": "", "snippet": "", "origin": "user"})
    text_all = " ".join([state["query"], a.condition, *a.keywords, *a.entities, *(x[1] for x in state.get("answers", []))])
    for u in github_release_feed(text_all):
        cands.append({"url": u, "title": "GitHub releases", "snippet": "", "origin": "feed", "kind": "feed"})
    for m in match_registry(text_all, CATEGORY_BY_KIND.get(a.kind)):
        cands.append({"url": m.entry.url, "title": m.entry.name, "snippet": ", ".join(m.matched), "origin": "registry",
                      "kind": m.entry.kind})
    if a.kind == "job" and a.company:
        for name, url in ats_candidates(a.company)[:6]:
            cands.append({"url": url, "title": f"{a.company} careers ({name})", "snippet": "", "origin": "ats",
                          "kind": "json"})
    if not state.get("urls"):
        queries = a.search_queries[:2] or [a.condition or state["query"]]
        for q in queries:
            try:
                hits = await get_search().search(q, max_results=6, country="IN")
            except SearchError as e:
                log.warning("intake_search_failed", error=str(e))
                continue
            for h in hits:
                cands.append({"url": h.url, "title": h.title, "snippet": h.snippet, "origin": "search"})
    seen: set[str] = set()
    uniq = []
    for c in cands:
        try:
            c["url"] = canonicalize_url(c["url"])
            validate_url(c["url"])
        except (SSRFBlocked, ValueError):
            continue
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        uniq.append(c)
    return {"candidates": uniq[: MAX_CANDIDATES + len(state.get("urls", []))]}


async def _probe(c: dict[str, Any]) -> dict[str, Any]:
    try:
        snap = await fetch_source(c["url"], max_age_seconds=3600, kind=c.get("kind", "page"), lock_wait_seconds=10)
    except SourceUnavailable as e:
        return {**c, "ok": False, "reason": e.reason, "error_kind": e.kind}
    except Exception as e:  # one bad candidate must never sink the whole intake
        log.warning("intake_probe_failed", url=c["url"], error=type(e).__name__)
        return {**c, "ok": False, "reason": "could not read this page", "error_kind": "error"}
    if len(snap.text.strip()) < 40:
        return {**c, "ok": False, "reason": "page has almost no readable text", "error_kind": "empty"}
    kind = "json" if (snap.structured or {}).get("json") else ("feed" if (snap.structured or {}).get("feed") else
                                                               c.get("kind", "page"))
    return {**c, "ok": True, "kind": kind, "final_url": snap.final_url, "page_title": snap.title or c.get("title", ""),
            "excerpt": snap.text[:1500], "snapshot_id": str(snap.snapshot_id), "text_len": len(snap.text)}


async def node_validate(state: IntakeState) -> dict[str, Any]:
    await _update_session(state, "running", "checking_pages", {"message": "Checking that the pages are reachable…"})
    sem = asyncio.Semaphore(4)

    async def guarded(c: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            return await _probe(c)

    results = await asyncio.gather(*(guarded(c) for c in state.get("candidates", [])))
    ok = [r for r in results if r["ok"]]
    if not ok:
        return {"validated": results, "chosen": [], "status": "need_url"}
    a = IntakeAnalysis.model_validate(state["analysis"])
    user_ok = [r for r in ok if r["origin"] == "user"]
    max_src = max(1, min(state.get("max_sources", 2), 3))
    if user_ok:
        chosen = user_ok[:max_src]
    elif len(ok) == 1:
        chosen = ok
    else:
        indexed = [(i, r["url"], r.get("page_title") or r.get("title", ""),
                    scan_and_strip(r["excerpt"]).cleaned_text[:900]) for i, r in enumerate(ok[:8])]
        try:
            res = await get_llm().structured(purpose="rank_sources", tier="fast", system=prompts.RANK_SYSTEM,
                                             user=prompts.rank_user(a.condition, indexed), schema=SourceRanking,
                                             max_tokens=600, **_llm_kwargs(state))
            picks = [c for c in res.data.choices if c.index < len(indexed) and c.relevance >= 0.4]
            picks.sort(key=lambda c: -c.relevance)
            chosen = [ok[c.index] for c in picks][:max_src]
        except LLMError:
            chosen = []
        if not chosen:
            pri = {"registry": 0, "ats": 1, "feed": 1, "search": 2}
            chosen = sorted(ok, key=lambda r: pri.get(r["origin"], 3))[:1]
    return {"validated": results, "chosen": chosen, "status": "ok"}


async def node_need_url(state: IntakeState) -> dict[str, Any]:
    failed = [r for r in state.get("validated", []) if not r.get("ok")]
    why = failed[0]["reason"] if failed else "I couldn't find an official page for this."
    asks = int(state.get("url_asks", 0))
    if asks >= 2:
        msg = f"I couldn't find a page I'm able to watch for this ({why}). Try a different site."
        await _update_session(state, "rejected", "done", {"message": msg, "reason_code": "no_source"})
        return {"status": "rejected", "message": msg}
    view = {"message": f"I couldn't find a page I can watch for this ({why}). Paste the link of the page that "
                       "would show it (for example the official notifications or careers page).",
            "questions": [{"id": "url", "question": "Which page should I watch?", "options": []}],
            "failed_sources": [{"url": r["url"], "reason": r.get("reason")} for r in failed[:5]]}
    await _update_session(state, "awaiting_user", "need_url", view)
    reply = interrupt({"type": "need_url"})
    raw = " ".join(str(v) for v in (reply.get("answers", {}) if isinstance(reply, dict) else {}).values())
    urls = extract_urls(raw if "://" in raw else raw.replace("www.", "https://www.", 1))
    cands = [{"url": u, "title": "", "snippet": "", "origin": "user"} for u in urls]
    return {"candidates": cands, "urls": urls, "url_asks": asks + 1}


async def node_compile(state: IntakeState) -> dict[str, Any]:
    a = IntakeAnalysis.model_validate(state["analysis"])
    preds: list[dict[str, Any]] = []
    dropped = False
    for sp in a.predicates:
        try:
            p = Predicate.model_validate(sp.model_dump(exclude_none=True))
            if p.type == "regex" and not p.pattern:
                continue
            preds.append(p.model_dump())
        except ValidationError:
            dropped = True
    mode = a.predicate_mode if preds else "none"
    if dropped and mode == "decide":
        mode = "prefilter"
    expires = None
    if a.expires_on:
        try:
            dt = dateparser.parse(a.expires_on)
            if dt and dt.replace(tzinfo=dt.tzinfo or UTC) > datetime.now(UTC):
                expires = dt.replace(tzinfo=dt.tzinfo or UTC).isoformat()
        except (ValueError, OverflowError):
            pass
    interval = clamp_interval(int(a.suggested_interval_minutes) * 60, _FakePlan(state["min_interval"]))
    sources = [{"url": c["url"], "kind": c.get("kind", "page"), "label": (c.get("page_title") or c.get("title") or "")[:120]}
               for c in state["chosen"]]
    data = {
        "kind": a.kind, "sources": sources, "condition": a.condition[:600], "predicates": preds,
        "predicate_mode": mode, "keywords": a.keywords[:20], "extract_fields": a.extract_fields[:12],
        "act": {"enabled": True, "tasks": a.act_tasks or ["extract_details", "deadlines"]},
        "interval_seconds": interval, "fire_once": a.fire_once, "expires_at": expires,
    }
    try:
        spec = WatchSpec.model_validate(data)
    except ValidationError:
        data.update({"predicates": [], "predicate_mode": "none"})
        spec = WatchSpec.model_validate(data)
    similar = await _similar_public(a, [s["url"] for s in sources])
    return {"spec": spec.model_dump(mode="json"), "similar": similar}


class _FakePlan:
    def __init__(self, min_interval: int):
        self._m = min_interval

    def limit(self, key: str) -> int:
        return self._m


async def _similar_public(a: IntakeAnalysis, urls: list[str]) -> list[dict[str, Any]]:
    async with session_scope() as s:
        rows = (await s.execute(text(
            """
            SELECT w.id, w.title, w.slug, w.subscriber_count, similarity(w.title, :q) AS sim
            FROM watches w
            WHERE w.visibility = 'public' AND w.status = 'active' AND w.moderation_status = 'approved'
              AND (w.title % :q OR EXISTS (
                    SELECT 1 FROM watch_versions v, jsonb_array_elements(v.spec->'sources') AS src
                    WHERE v.id = w.current_version_id AND src->>'url' = ANY(CAST(:urls AS text[]))))
            ORDER BY sim DESC, w.subscriber_count DESC LIMIT 3
            """
        ), {"q": a.title or a.condition, "urls": urls})).all()
    return [{"watch_id": str(r.id), "title": r.title, "slug": r.slug, "subscribers": r.subscriber_count}
            for r in rows]


async def node_dry_run(state: IntakeState) -> dict[str, Any]:
    await _update_session(state, "running", "testing", {"message": "Testing the watch against the page right now…"})
    spec = WatchSpec.model_validate(state["spec"])
    by_url = {c["url"]: c for c in state["chosen"]}
    texts = []
    for src in spec.sources:
        try:
            snap = await fetch_source(src.url, max_age_seconds=3600, kind=src.kind)
            texts.append((snap.text, snap.structured, snap.links))
        except SourceUnavailable:
            continue
    if not texts:
        return {"dry_run": {"already_met": False, "reason": "Could not re-read the page for a test.", "evidence": ""}}
    if spec.predicate_mode == "decide":
        for t, st, _links in texts:
            r = eval_all(spec.predicates, ViewContext(text=t, diff=None, new_items=[], structured=st, changed=False))
            level = all(p.type not in ("new_items", "text_changed") and p.scope == "page" for p in spec.predicates)
            if r.passed and level:
                return {"dry_run": {"already_met": True, "reason": "; ".join(r.explanations[:3]),
                                    "evidence": r.evidence or ""}}
        return {"dry_run": {"already_met": False, "reason": "Not true yet: " + "; ".join(
            eval_all(spec.predicates, ViewContext(text=texts[0][0], diff=None, new_items=[], structured=texts[0][1],
                                                  changed=False)).explanations[:2]), "evidence": ""}}
    context = scan_and_strip("\n\n".join(t[0][:4000] for t in texts)).cleaned_text
    try:
        res = await get_llm().structured(purpose="dry_run", tier="fast", system=prompts.DRYRUN_SYSTEM,
                                         user=prompts.dryrun_user(spec.condition, prompts.now_ist_str(), context),
                                         schema=DryRunOut, max_tokens=400, **_llm_kwargs(state))
        d = res.data
        met = d.already_met and quote_in_text(d.evidence_quote, context)
        return {"dry_run": {"already_met": met, "reason": d.reason, "evidence": d.evidence_quote if met else ""}}
    except LLMError:
        return {"dry_run": {"already_met": False, "reason": "Skipped the live test (AI busy).", "evidence": ""}}
    finally:
        _ = by_url


def _proposal_view(state: IntakeState) -> dict[str, Any]:
    a = IntakeAnalysis.model_validate(state["analysis"])
    spec = WatchSpec.model_validate(state["spec"])
    return {
        "message": "Here's the watch I'll set up. Confirm or adjust:",
        "proposal": {
            "title": a.title or spec.condition[:80], "condition": spec.condition, "kind": spec.kind,
            "category": CATEGORY_BY_KIND.get(spec.kind, "other"),
            "sources": [{"url": s.url, "label": s.label, "kind": s.kind} for s in spec.sources],
            "interval_minutes": spec.interval_seconds // 60, "min_interval_minutes": state["min_interval"] // 60,
            "rules": [p.model_dump(exclude_none=True) for p in spec.predicates], "rule_mode": spec.predicate_mode,
            "uses_ai_judgement": spec.predicate_mode != "decide", "fire_once": spec.fire_once,
            "expires_at": spec.expires_at.isoformat() if spec.expires_at else None,
            "follow_up_tasks": spec.act.tasks, "extract_fields": spec.extract_fields,
        },
        "dry_run": state.get("dry_run"), "similar_public_watches": state.get("similar", []),
    }


async def node_propose(state: IntakeState) -> dict[str, Any]:
    view = _proposal_view(state)
    await _update_session(state, "proposed", "confirm", view)
    reply = interrupt({"type": "confirm"})
    if not isinstance(reply, dict) or not reply.get("confirm"):
        await _update_session(state, "cancelled", "done", {"message": "Okay, I didn't create the watch."})
        return {"status": "cancelled"}
    return {"status": "confirmed", "edits": dict(reply.get("edits") or {})}


async def node_create(state: IntakeState) -> dict[str, Any]:
    from app.core.errors import AppError
    from app.services.watches import create_watch

    a = IntakeAnalysis.model_validate(state["analysis"])
    edits = state.get("edits") or {}
    spec_data = dict(state["spec"])
    if edits.get("interval_minutes"):
        spec_data["interval_seconds"] = max(int(edits["interval_minutes"]) * 60, state["min_interval"])
    if edits.get("condition"):
        spec_data["condition"] = str(edits["condition"])[:600]
    if "fire_once" in edits:
        spec_data["fire_once"] = bool(edits["fire_once"])
    try:
        spec = WatchSpec.model_validate(spec_data)
    except ValidationError as e:
        msg = f"Those edits aren't valid: {e.errors()[0].get('msg', 'invalid')}"
        await _update_session(state, "proposed", "confirm", {**_proposal_view(state), "error": msg})
        return {"status": "edit_invalid", "message": msg}
    title = str(edits.get("title") or a.title or spec.condition[:80])[:140]
    try:
        async with session_scope() as s:
            prof = await s.get(Profile, uuid.UUID(state["user_id"]))
            plan = await get_plan(s, effective_plan_id(prof))
            w = await create_watch(
                s, owner=prof, plan=plan, spec=spec, title=title, query_text=state["query"],
                category=CATEGORY_BY_KIND.get(spec.kind, "other"),
                description=a.condition[:500], visibility=str(edits.get("visibility", "private")),
                created_by="intake", changelog="Created by the intake agent",
                delivery_mode=edits.get("delivery_mode") if edits.get("delivery_mode") in ("instant", "digest") else None,
                tags=[e[:40] for e in a.entities[:5]], run_soon=False,
            )
            watch_id = w.id
            # Baseline: the page as it is right now, so the first scheduled run only reacts to NEW changes.
            for c in state["chosen"]:
                snap = await fetch_source(c["url"], max_age_seconds=3600, kind=c.get("kind", "page"))
                s.add(WatchSourceState(watch_id=watch_id, source_url=c["url"], view_hash=content_hash(snap.text),
                                       view_text=snap.text, items=snap.links[:500], snapshot_id=snap.snapshot_id))
            row = await s.get(IntakeSession, uuid.UUID(state["session_id"]))
            if row is not None:
                row.watch_id = watch_id
    except AppError as e:
        await _update_session(state, "failed", "done", {"message": e.message, "reason_code": e.code,
                                                        "details": e.details})
        return {"status": "failed", "message": e.message}
    except SourceUnavailable as e:
        await _update_session(state, "failed", "done", {"message": f"The page became unavailable: {e.reason}"})
        return {"status": "failed", "message": e.reason}
    st = {**state, "watch_id": str(watch_id)}
    view = {"message": "Your watch is live.", "watch_id": str(watch_id), "title": title,
            "dry_run": state.get("dry_run")}
    await _update_session(st, "created", "done", view)  # type: ignore[arg-type]
    return {"status": "created", "watch_id": str(watch_id)}


# ------------------------------------------------------------------ routing / graph
def _after_analyze(state: IntakeState) -> str:
    st = state.get("status")
    if st == "clarify":
        return "clarify"
    if st == "ok":
        return "discover"
    return END


def _after_validate(state: IntakeState) -> str:
    return "need_url" if state.get("status") == "need_url" else "compile"


def _after_need_url(state: IntakeState) -> str:
    return END if state.get("status") == "rejected" else "validate"


def _after_propose(state: IntakeState) -> str:
    return "create" if state.get("status") == "confirmed" else END


def _after_create(state: IntakeState) -> str:
    return "propose" if state.get("status") == "edit_invalid" else END


def build_intake_graph(checkpointer: Any) -> Any:
    g = StateGraph(IntakeState)
    g.add_node("analyze", node_analyze)
    g.add_node("clarify", node_clarify)
    g.add_node("discover", node_discover)
    g.add_node("validate", node_validate)
    g.add_node("need_url", node_need_url)
    g.add_node("compile", node_compile)
    g.add_node("dry_run", node_dry_run)
    g.add_node("propose", node_propose)
    g.add_node("create", node_create)
    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", _after_analyze, ["clarify", "discover", END])
    g.add_edge("clarify", "analyze")
    g.add_edge("discover", "validate")
    g.add_conditional_edges("validate", _after_validate, ["need_url", "compile"])
    g.add_conditional_edges("need_url", _after_need_url, ["validate", END])
    g.add_edge("compile", "dry_run")
    g.add_edge("dry_run", "propose")
    g.add_conditional_edges("propose", _after_propose, ["create", END])
    g.add_conditional_edges("create", _after_create, ["propose", END])
    return g.compile(checkpointer=checkpointer)


async def recent_similar_session(user_id: uuid.UUID, query: str) -> uuid.UUID | None:
    """Duplicate-submission guard: same user, same text, still in progress, within 10 minutes."""
    async with session_scope() as s:
        return await s.scalar(
            select(IntakeSession.id).where(
                IntakeSession.user_id == user_id, func.lower(IntakeSession.query) == query.strip().lower(),
                IntakeSession.status.in_(("queued", "running", "awaiting_user", "proposed")),
                IntakeSession.created_at > datetime.now(UTC) - timedelta(minutes=10),
            ).limit(1)
        )
