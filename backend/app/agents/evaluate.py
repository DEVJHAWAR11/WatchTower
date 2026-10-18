"""Evaluation graph: runs on every scheduled check.

    fetch -> change_gate -> [rules] -> [triage] -> judge -> dedup -> fire
                 |             |          |          |        |
                 +-------------+----------+----------+--------+--> END (each node may decide early)

Cost ladder: unchanged hash (free) -> learned-noise (free) -> deterministic rules (free) -> fast-model triage
(cheap) -> smart-model judge (only when needed, cached by content). Every node appends a human-readable step to
the run so the live view can say exactly what happened and why.
"""

from __future__ import annotations

import operator
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agents import prompts
from app.agents.predicates import ViewContext, eval_all
from app.agents.schemas import JudgeOut, TriageOut
from app.core.config import get_settings
from app.core.crypto import sha256_hex
from app.core.db import session_scope
from app.core.logging import get_logger
from app.fetch.diff import TextDiff, diff_lines, new_items
from app.fetch.normalize import content_hash, line_signature
from app.fetch.service import SourceUnavailable, fetch_source, view_for
from app.llm.client import LLMBudgetExceeded, LLMError, get_llm
from app.llm.safety import quote_in_text, scan_and_strip
from app.models import Alert, Profile, Run, Watch, WatchSourceState, WatchVersion
from app.observability.metrics import AGENT_NODE_SECONDS, ALERTS_TOTAL, RUN_DURATION, RUNS_TOTAL
from app.realtime.events import publish_watch
from app.schemas.spec import WatchSpec
from app.services.plans import effective_plan_id, get_plan

log = get_logger(__name__)

LEVEL_PREDICATES = {"price_below", "price_above", "number_below", "number_above", "in_stock", "contains_any",
                    "contains_all", "not_contains", "regex"}
MAX_CONTEXT_CHARS = 6000
MAX_DIFF_CHARS = 5000
NOISE_CAP = 300
COMMUNITY_SUBSCRIBERS = 10


class EvalState(TypedDict, total=False):
    run_id: str
    watch_id: str
    version_id: str
    trigger: str
    spec: dict[str, Any]
    watch_title: str
    owner_id: str
    plan_id: str
    token_limit: int | None
    max_age: int
    noise: list[str]
    eval_state: dict[str, Any]
    views: list[dict[str, Any]]
    source_errors: list[dict[str, Any]]
    done: bool
    defer: bool
    outcome: str
    decided_by: str
    reason: str
    confidence: float | None
    verdict: dict[str, Any]
    llm_called: bool
    llm_tokens: Annotated[int, operator.add]
    llm_cost: Annotated[float, operator.add]
    steps: Annotated[list[dict[str, Any]], operator.add]
    alert_id: str | None
    learn_noise: list[str]
    known_events: list[str]


def _step(node: str, status: str, note: str, started: float, **extra: Any) -> dict[str, Any]:
    ms = int((time.monotonic() - started) * 1000)
    AGENT_NODE_SECONDS.labels(graph="evaluate", node=node).observe(ms / 1000)
    return {"node": node, "status": status, "note": note[:500], "ms": ms, "at": datetime.now(UTC).isoformat(), **extra}


async def _emit(state: EvalState, step: dict[str, Any]) -> None:
    await publish_watch(state["watch_id"], "run.step", {"run_id": state["run_id"], **step})


# ------------------------------------------------------------------ nodes
async def node_fetch(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    spec = WatchSpec.model_validate(state["spec"])
    views: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for src in spec.sources:
        try:
            snap = await fetch_source(src.url, max_age_seconds=state["max_age"], kind=src.kind,
                                      force_render=src.fetch_mode == "render")
        except SourceUnavailable as e:
            errors.append({"url": src.url, "kind": e.kind, "reason": e.reason, "retry_after": e.retry_after})
            continue
        text, links, matched = view_for(snap, src.selector)
        views.append({
            "url": src.url, "final_url": snap.final_url, "snapshot_id": str(snap.snapshot_id), "text": text,
            "links": links, "structured": snap.structured, "title": snap.title, "selector": src.selector,
            "selector_matched": matched, "from_cache": snap.from_cache,
        })
    if not views:
        kinds = {e["kind"] for e in errors}
        if kinds <= {"busy"}:
            outcome, why = "deferred", "Site busy or rate-limited; will retry shortly"
        elif kinds <= {"blocked", "robots"}:
            outcome, why = "blocked", errors[0]["reason"]
        else:
            outcome, why = "error", errors[0]["reason"] if errors else "No sources"
        step = _step("fetch", "failed", why, t0, errors=errors)
        await _emit(state, step)
        return {"views": [], "source_errors": errors, "done": True, "defer": True, "outcome": outcome,
                "decided_by": "none", "reason": why, "steps": [step]}
    parts = []
    for v in views:
        parts.append(f"{v['url']} ({'reused recent copy' if v['from_cache'] else 'fetched'})")
        if v["selector"] and v["selector_matched"] is False:
            parts.append(f"selector '{v['selector']}' no longer matches; used full page")
    if errors:
        parts.append(f"{len(errors)} source(s) unavailable: {errors[0]['reason']}")
    step = _step("fetch", "ok", "; ".join(parts), t0)
    await _emit(state, step)
    return {"views": views, "source_errors": errors, "steps": [step]}


async def node_gate(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    async with session_scope() as s:
        rows = (await s.execute(
            select(WatchSourceState).where(WatchSourceState.watch_id == uuid.UUID(state["watch_id"]))
        )).scalars().all()
        prev = {r.source_url: (r.view_hash, r.view_text, list(r.items or [])) for r in rows}
    noise = set(state.get("noise") or [])
    views = []
    changed = baseline = 0
    noise_only = True
    for v in state["views"]:
        v = dict(v)
        v["new_hash"] = content_hash(v["text"])
        p = prev.get(v["url"])
        if p is None:
            v["status"] = "baseline"
            baseline += 1
        elif p[0] == v["new_hash"]:
            v["status"] = "unchanged"
        else:
            d = diff_lines(p[1], v["text"])
            ni = new_items(p[2], v["links"])
            if d.is_empty and not ni:
                v["status"] = "unchanged"
            else:
                v["status"] = "changed"
                v["diff_added"] = d.added
                v["diff_removed"] = d.removed
                v["new_items"] = ni[:50]
                paired = _paired_signatures(d)
                if ni or not paired["all_paired"] or not paired["sigs"] <= noise:
                    noise_only = False
                changed += 1
        views.append(v)
    if changed == 0:
        if baseline and baseline == len(views):
            why = "First check: recorded the page as a baseline. Future changes will be evaluated."
            outcome, by = "baseline", "none"
        else:
            why = "No meaningful change since the last check, so the AI was not called."
            outcome, by = "skipped_unchanged", "hash"
        step = _step("change_gate", "skip", why, t0)
        await _emit(state, step)
        return {"views": views, "done": True, "outcome": outcome, "decided_by": by, "reason": why, "steps": [step]}
    if noise_only:
        why = "Only lines that are known to change constantly (counters, timestamps) changed, so the AI was not called."
        step = _step("change_gate", "skip", why, t0)
        await _emit(state, step)
        return {"views": views, "done": True, "outcome": "skipped_unchanged", "decided_by": "noise",
                "reason": why, "steps": [step]}
    summ = []
    for v in views:
        if v["status"] == "changed":
            summ.append(f"+{len(v['diff_added'])}/-{len(v['diff_removed'])} lines, {len(v['new_items'])} new links")
    step = _step("change_gate", "changed", "Page changed: " + "; ".join(summ), t0)
    await _emit(state, step)
    return {"views": views, "steps": [step]}


def _paired_signatures(d: TextDiff) -> dict[str, Any]:
    """Lines that changed only in their numbers (same signature removed+added): candidates for noise learning."""
    added = [line_signature(x) for x in d.added]
    removed = [line_signature(x) for x in d.removed]
    rem_pool = list(removed)
    all_paired = True
    for sig in added:
        if sig in rem_pool:
            rem_pool.remove(sig)
        else:
            all_paired = False
    return {"all_paired": all_paired and not rem_pool, "sigs": set(added) | set(removed)}


def _ctx_for(v: dict[str, Any]) -> ViewContext:
    d = TextDiff(added=v.get("diff_added", []), removed=v.get("diff_removed", [])) if v["status"] == "changed" else None
    return ViewContext(text=v["text"], diff=d, new_items=v.get("new_items", []), structured=v.get("structured", {}),
                       changed=v["status"] == "changed")


async def node_rules(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    spec = WatchSpec.model_validate(state["spec"])
    est = dict(state.get("eval_state") or {})
    passing = None
    passing_view = None
    explanations: list[str] = []
    for v in state["views"]:
        r = eval_all(spec.predicates, _ctx_for(v))
        explanations.extend(r.explanations)
        if r.passed and passing is None:
            passing, passing_view = r, v
    level = all(p.type in LEVEL_PREDICATES and p.scope == "page" for p in spec.predicates)
    prev_passed = bool(est.get("rule_passed"))
    est["rule_passed"] = passing is not None
    note = "; ".join(explanations[:4]) or "rules evaluated"
    if spec.predicate_mode == "prefilter":
        if passing is None:
            step = _step("rules", "no_match", f"Rules did not pass, AI not needed: {note}", t0)
            await _emit(state, step)
            return {"done": True, "outcome": "no_match", "decided_by": "rule", "reason": step["note"],
                    "eval_state": est, "steps": [step]}
        step = _step("rules", "pass", f"Rules passed ({note}); asking AI to confirm", t0)
        await _emit(state, step)
        return {"eval_state": est, "steps": [step]}

    # decide mode
    if passing is None:
        step = _step("rules", "no_match", f"Condition not met: {note}", t0)
        await _emit(state, step)
        return {"done": True, "outcome": "no_match", "decided_by": "rule", "reason": step["note"],
                "eval_state": est, "steps": [step]}
    assert passing_view is not None
    facts: dict[str, Any] = {k: v for k, v in passing.facts.items() if k != "new_items"}
    if level:
        price = passing.facts.get("price")
        last_price = est.get("alerted_price")
        dropped_more = price is not None and last_price is not None and float(price) <= float(last_price) * 0.97
        if prev_passed and not dropped_more:
            step = _step("rules", "still_true", f"Condition still true ({note}); already alerted for this.", t0)
            await _emit(state, step)
            return {"done": True, "outcome": "duplicate", "decided_by": "rule", "reason": step["note"],
                    "eval_state": est, "steps": [step]}
        est["episode"] = int(est.get("episode", 0)) + (0 if dropped_more else 1)
        if price is not None:
            est["alerted_price"] = price
        event_key = f"rule episode {est['episode']}" + (f" price {price}" if price is not None else "")
    else:
        items = passing.facts.get("new_items") or []
        keyset = sorted(f"{i.get('text', '')}|{i.get('href', '')}" for i in items) or [passing.evidence or note]
        event_key = "items " + sha256_hex(*keyset)[:16]
        if items:
            facts["new_items"] = "; ".join(i.get("text", "")[:80] for i in items[:5])
    summary = "; ".join(passing.explanations[:3])
    verdict = {
        "title": f"{state['watch_title'][:90]}",
        "summary": summary[:800], "key_facts": {k: str(v)[:400] for k, v in facts.items()},
        "evidence": (passing.evidence or "")[:600], "event_key": event_key,
        "source_url": passing_view["final_url"], "context_excerpt": _context(passing_view, spec)[:MAX_CONTEXT_CHARS],
    }
    step = _step("rules", "match", f"Condition met by rule: {summary}", t0)
    await _emit(state, step)
    return {"outcome": "matched", "decided_by": "rule", "reason": step["note"], "confidence": 1.0,
            "verdict": verdict, "eval_state": est, "steps": [step]}


def _changed_text(views: list[dict[str, Any]], max_chars: int = MAX_DIFF_CHARS) -> str:
    out: list[str] = []
    total = 0
    for v in views:
        if v["status"] != "changed":
            continue
        for line in v.get("diff_added", []):
            s = f"+ {line}"
            total += len(s)
            if total > max_chars:
                return "\n".join(out)
            out.append(s)
        for line in v.get("diff_removed", [])[:30]:
            s = f"- {line}"
            total += len(s)
            if total > max_chars:
                return "\n".join(out)
            out.append(s)
    return "\n".join(out)


def _context(v: dict[str, Any], spec: WatchSpec, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    lines = v["text"].splitlines()
    terms = [k.lower() for k in spec.keywords if len(k) >= 3]
    for p in spec.predicates:
        terms += [x.lower() for x in p.values if len(x) >= 3]
    added = {a.strip() for a in v.get("diff_added", [])}
    hits = [i for i, line in enumerate(lines) if line.strip() in added or any(t in line.lower() for t in terms)]
    if not hits:
        return v["text"][:max_chars]
    keep: set[int] = set()
    for i in hits[:200]:
        keep.update(range(max(0, i - 3), min(len(lines), i + 4)))
    out: list[str] = []
    last = -2
    total = 0
    for i in sorted(keep):
        if i != last + 1:
            out.append("…")
        out.append(lines[i])
        total += len(lines[i]) + 1
        last = i
        if total > max_chars:
            break
    return "\n".join(out)[:max_chars]


def _llm_error_result(state: EvalState, node: str, e: Exception, t0: float) -> dict[str, Any]:
    if isinstance(e, LLMBudgetExceeded):
        why = f"AI check postponed: {e}. The change will be re-checked later."
        outcome = "deferred"
    else:
        why = "AI service unavailable; the change will be re-checked on the next run (no false 'no change')."
        outcome = "error"
    return {"done": True, "defer": True, "outcome": outcome, "decided_by": "none", "reason": why,
            "steps": [_step(node, "failed", why, t0, error=type(e).__name__)]}


async def node_triage(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    spec = WatchSpec.model_validate(state["spec"])
    changed = _changed_text(state["views"])
    items = "\n".join(i.get("text", "") for v in state["views"] for i in v.get("new_items", []))[:2000]
    if len(changed) + len(items) < get_settings().triage_min_diff_chars:
        return {}  # small change: go straight to the judge, triage would not save money
    scan = scan_and_strip(changed + ("\n" + items if items else ""))
    try:
        res = await get_llm().structured(
            purpose="triage", tier="fast", system=prompts.TRIAGE_SYSTEM,
            user=prompts.triage_user(spec.condition, spec.keywords, scan.cleaned_text),
            schema=TriageOut, user_id=uuid.UUID(state["owner_id"]), plan_id=state["plan_id"],
            token_limit_per_day=state.get("token_limit"), max_tokens=300,
        )
    except LLMError as e:
        out = _llm_error_result(state, "triage", e, t0)
        await _emit(state, out["steps"][0])
        return out
    upd: dict[str, Any] = {"llm_called": True, "llm_tokens": res.total_tokens, "llm_cost": res.cost_usd}
    if not res.data.plausibly_relevant:
        why = f"Quick AI screen: change is unrelated ({res.data.reason or 'no relevant lines'})."
        step = _step("triage", "no_match", why, t0, model=res.model, cached=res.cached)
        await _emit(state, step)
        learn = sorted(_noise_candidates(state["views"]))
        return {**upd, "done": True, "outcome": "no_match", "decided_by": "triage", "reason": why,
                "learn_noise": learn, "steps": [step]}
    step = _step("triage", "pass", "Quick AI screen: change may be relevant; running full check", t0,
                 model=res.model, cached=res.cached)
    await _emit(state, step)
    return {**upd, "steps": [step]}


def _noise_candidates(views: list[dict[str, Any]]) -> set[str]:
    sigs: set[str] = set()
    for v in views:
        if v.get("status") != "changed" or v.get("new_items"):
            continue
        d = TextDiff(added=v.get("diff_added", []), removed=v.get("diff_removed", []))
        p = _paired_signatures(d)
        if p["all_paired"]:
            sigs |= p["sigs"]
    return sigs


async def node_judge(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    spec = WatchSpec.model_validate(state["spec"])
    changed_views = [v for v in state["views"] if v["status"] == "changed"] or state["views"]
    primary = changed_views[0]
    changed = _changed_text(state["views"])
    items = "\n".join(f"- {i.get('text', '')} ({i.get('href', '')})" for v in changed_views
                      for i in v.get("new_items", [])[:30])[:3000]
    context = "\n\n".join(_context(v, spec, MAX_CONTEXT_CHARS // len(changed_views)) for v in changed_views)
    scans = [scan_and_strip(changed), scan_and_strip(items), scan_and_strip(context)]
    suspicious = [ln for sc in scans for ln in sc.suspicious_lines]
    changed, items, context = (sc.cleaned_text for sc in scans)
    try:
        res = await get_llm().structured(
            purpose="judge", tier="smart", system=prompts.JUDGE_SYSTEM,
            user=prompts.judge_user(
                condition=spec.condition, now=prompts.now_ist_str(), positives=spec.positive_examples,
                negatives=spec.negative_examples, known_events=state.get("known_events") or [],
                source_url=primary["final_url"], changed=changed, context=context, new_items=items,
            ),
            schema=JudgeOut, user_id=uuid.UUID(state["owner_id"]), plan_id=state["plan_id"],
            token_limit_per_day=state.get("token_limit"), max_tokens=900,
        )
    except LLMError as e:
        out = _llm_error_result(state, "judge", e, t0)
        await _emit(state, out["steps"][0])
        return out
    j = res.data
    upd: dict[str, Any] = {"llm_called": True, "llm_tokens": res.total_tokens, "llm_cost": res.cost_usd,
                           "confidence": j.confidence}
    min_conf = get_settings().judge_min_confidence
    if suspicious:
        min_conf = max(min_conf, 0.8)
    all_text = "\n".join(v["text"] for v in state["views"]) + "\n" + items
    extra = {"model": res.model, "cached": res.cached}
    if suspicious:
        extra["injection_lines_removed"] = len(suspicious)
    if not j.condition_met:
        why = f"AI judged the condition not met ({j.confidence:.0%} confident): {j.reason}"
        step = _step("judge", "no_match", why, t0, **extra)
        await _emit(state, step)
        learn = sorted(_noise_candidates(state["views"])) if j.confidence >= 0.7 else []
        return {**upd, "done": True, "outcome": "no_match", "decided_by": "llm", "reason": why,
                "learn_noise": learn, "steps": [step]}
    if j.is_repeat_of_known_event:
        why = f"AI found the condition met, but it is the same event you were already alerted about ({j.event_key})."
        step = _step("judge", "duplicate", why, t0, **extra)
        await _emit(state, step)
        return {**upd, "done": True, "outcome": "duplicate", "decided_by": "llm", "reason": why, "steps": [step]}
    if not quote_in_text(j.evidence_quote, all_text):
        why = "AI claimed a match but its evidence quote could not be found on the page, so no alert was sent."
        step = _step("judge", "rejected", why, t0, **extra)
        await _emit(state, step)
        return {**upd, "done": True, "outcome": "no_match", "decided_by": "llm", "reason": why, "steps": [step]}
    if j.confidence < min_conf:
        why = f"AI saw a possible match but confidence {j.confidence:.0%} is below the {min_conf:.0%} bar: {j.reason}"
        step = _step("judge", "low_confidence", why, t0, **extra)
        await _emit(state, step)
        return {**upd, "done": True, "outcome": "no_match", "decided_by": "llm", "reason": why, "steps": [step]}
    verdict = {
        "title": (j.title or state["watch_title"])[:140], "summary": j.summary[:800], "key_facts": j.facts_dict(),
        "evidence": j.evidence_quote[:600], "event_key": j.event_key or j.title,
        "source_url": primary["final_url"], "context_excerpt": (changed + "\n\n" + context)[:MAX_CONTEXT_CHARS],
    }
    why = f"AI confirmed the condition is met ({j.confidence:.0%} confident): {j.reason}"
    step = _step("judge", "match", why, t0, **extra)
    await _emit(state, step)
    return {**upd, "outcome": "matched", "decided_by": "cache" if res.cached else "llm", "reason": why,
            "verdict": verdict, "steps": [step]}


_TOK = re.compile(r"[a-z0-9]+")


def event_tokens(key: str) -> set[str]:
    return set(_TOK.findall(key.lower()))


def fingerprint_for(event_key: str) -> str:
    return sha256_hex(" ".join(sorted(event_tokens(event_key))))


async def node_dedup(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    spec = WatchSpec.model_validate(state["spec"])
    v = state["verdict"]
    fp = fingerprint_for(v["event_key"] or v["evidence"] or v["title"])
    since = datetime.now(UTC) - timedelta(days=spec.dedup_window_days)
    async with session_scope() as s:
        recent = (await s.execute(
            select(Alert.fingerprint, Alert.event_key, Alert.title, Alert.created_at, Alert.evidence)
            .where(Alert.watch_id == uuid.UUID(state["watch_id"]))
            .order_by(Alert.created_at.desc()).limit(100)
        )).all()
    toks = event_tokens(v["event_key"] or "")
    ev_toks = event_tokens(v.get("evidence") or "")
    for r in recent:
        if r.fingerprint == fp:
            why = f"Already alerted about this on {r.created_at:%d %b %Y} ('{r.title[:60]}')."
            step = _step("dedup", "duplicate", why, t0)
            await _emit(state, step)
            return {"done": True, "outcome": "duplicate", "reason": why, "steps": [step]}
        if r.created_at >= since and toks and r.event_key and state.get("decided_by") != "rule":
            other = event_tokens(r.event_key)
            prev_ev = event_tokens(r.evidence or "")
            if len(prev_ev) >= 4 and prev_ev <= ev_toks:
                why = f"Same item you were alerted about on {r.created_at:%d %b} ('{r.title[:60]}')."
                step = _step("dedup", "duplicate", why, t0)
                await _emit(state, step)
                return {"done": True, "outcome": "duplicate", "reason": why, "steps": [step]}
            if other and len(toks & other) / len(toks | other) >= 0.8:
                why = f"Very similar to an alert from {r.created_at:%d %b} ('{r.title[:60]}'); not alerting twice."
                step = _step("dedup", "duplicate", why, t0)
                await _emit(state, step)
                return {"done": True, "outcome": "duplicate", "reason": why, "steps": [step]}
    step = _step("dedup", "new", "This is a new event.", t0)
    await _emit(state, step)
    return {"verdict": {**v, "fingerprint": fp}, "steps": [step]}


async def node_fire(state: EvalState) -> dict[str, Any]:
    t0 = time.monotonic()
    v = state["verdict"]
    spec = WatchSpec.model_validate(state["spec"])
    wid = uuid.UUID(state["watch_id"])
    async with session_scope() as s:
        res = await s.execute(
            pg_insert(Alert).values(
                watch_id=wid, version_id=uuid.UUID(state["version_id"]), run_id=uuid.UUID(state["run_id"]),
                fingerprint=v["fingerprint"], event_key=v["event_key"][:500], title=v["title"][:200] or "Watch fired",
                summary=v["summary"] or v["title"], key_facts=v["key_facts"], evidence=v["evidence"],
                context_excerpt=v["context_excerpt"], source_url=v["source_url"], confidence=state.get("confidence"),
                decided_by=state.get("decided_by", "llm"),
                act_status="pending" if spec.act.enabled else "skipped",
            ).on_conflict_do_nothing(index_elements=["watch_id", "fingerprint"]).returning(Alert.id)
        )
        alert_id = res.scalar_one_or_none()
        if alert_id is None:
            why = "Already alerted about this event."
            step = _step("fire", "duplicate", why, t0)
            await _emit(state, step)
            return {"done": True, "outcome": "duplicate", "reason": why, "steps": [step]}
        w = await s.get(Watch, wid, with_for_update=True)
        assert w is not None
        w.alert_count = (w.alert_count or 0) + 1
        w.last_alert_at = datetime.now(UTC)
        if spec.fire_once:
            w.status = "completed"
            w.status_reason = "One-time event happened; watch completed."
    ALERTS_TOTAL.labels(decided_by=state.get("decided_by", "llm")).inc()
    step = _step("fire", "alert", f"Alert created: {v['title'][:100]}", t0, alert_id=str(alert_id))
    await _emit(state, step)
    return {"alert_id": str(alert_id), "steps": [step]}


# ------------------------------------------------------------------ graph
def _after(next_node: str):  # noqa: ANN202
    def route(state: EvalState) -> str:
        return END if state.get("done") else next_node
    return route


def _after_gate(state: EvalState) -> str:
    if state.get("done"):
        return END
    mode = state["spec"].get("predicate_mode", "none")
    return "rules" if mode in ("decide", "prefilter") and state["spec"].get("predicates") else "triage"


def _after_rules(state: EvalState) -> str:
    if state.get("done"):
        return END
    return "dedup" if state.get("outcome") == "matched" else "triage"


def build_eval_graph() -> Any:
    g = StateGraph(EvalState)
    g.add_node("fetch", node_fetch)
    g.add_node("change_gate", node_gate)
    g.add_node("rules", node_rules)
    g.add_node("triage", node_triage)
    g.add_node("judge", node_judge)
    g.add_node("dedup", node_dedup)
    g.add_node("fire", node_fire)
    g.add_edge(START, "fetch")
    g.add_conditional_edges("fetch", _after("change_gate"), ["change_gate", END])
    g.add_conditional_edges("change_gate", _after_gate, ["rules", "triage", END])
    g.add_conditional_edges("rules", _after_rules, ["dedup", "triage", END])
    g.add_conditional_edges("triage", _after("judge"), ["judge", END])
    g.add_conditional_edges("judge", _after("dedup"), ["dedup", END])
    g.add_conditional_edges("dedup", _after("fire"), ["fire", END])
    g.add_edge("fire", END)
    return g.compile()


_graph: Any = None


def eval_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_eval_graph()
    return _graph


# ------------------------------------------------------------------ entrypoint
class RunSummary(TypedDict):
    run_id: str
    outcome: str
    decided_by: str
    reason: str
    alert_id: str | None
    llm_called: bool
    retry_after: int | None
    failed: bool


async def run_evaluation(watch_id: uuid.UUID, *, trigger: str = "schedule") -> RunSummary:
    started = time.monotonic()
    async with session_scope() as s:
        w = await s.get(Watch, watch_id)
        if w is None or w.current_version_id is None:
            raise LookupError("watch not found or has no version")
        ver = await s.get(WatchVersion, w.current_version_id)
        owner = await s.get(Profile, w.owner_id)
        assert ver is not None and owner is not None
        plan = await get_plan(s, effective_plan_id(owner))
        community = w.visibility == "public" and w.subscriber_count >= COMMUNITY_SUBSCRIBERS
        recent = (await s.execute(
            select(Alert.event_key).where(Alert.watch_id == w.id).order_by(Alert.created_at.desc()).limit(10)
        )).scalars().all()
        run = Run(watch_id=w.id, version_id=ver.id, trigger=trigger, status="running")
        s.add(run)
        await s.flush()
        spec = WatchSpec.model_validate(ver.spec)
        state: EvalState = {
            "run_id": str(run.id), "watch_id": str(w.id), "version_id": str(ver.id), "trigger": trigger,
            "spec": ver.spec, "watch_title": w.title, "owner_id": str(w.owner_id),
            "plan_id": "pro" if community else plan.id,
            "token_limit": None if community else plan.limit("llm_tokens_per_day"),
            "max_age": 0 if trigger == "manual" else max(60, min(spec.interval_seconds // 2, 600)),
            "noise": list(w.noise_signatures or []), "eval_state": dict(w.eval_state or {}),
            "known_events": [k for k in recent if k], "steps": [], "llm_tokens": 0, "llm_cost": 0.0,
        }
        run_id = run.id
    await publish_watch(watch_id, "run.started", {"run_id": str(run_id), "trigger": trigger})
    final: EvalState
    failed = False
    try:
        final = await eval_graph().ainvoke(state)
    except Exception as e:  # never leave a run dangling
        log.exception("evaluation_crashed", watch_id=str(watch_id), run_id=str(run_id))
        failed = True
        final = {**state, "outcome": "error", "decided_by": "none", "defer": True,
                 "reason": f"Internal error during check ({type(e).__name__}); will retry.",
                 "steps": state.get("steps", []) + [{"node": "internal", "status": "failed", "note": str(e)[:300]}]}
    outcome = final.get("outcome") or "no_match"
    decided_by = final.get("decided_by") or "none"
    reason = final.get("reason") or ""
    alert_id = final.get("alert_id")
    retry_after = None
    for err in final.get("source_errors") or []:
        if err.get("retry_after"):
            retry_after = max(retry_after or 0, int(err["retry_after"]))
    await _persist(watch_id, run_id, final, outcome, decided_by, reason, started)
    RUNS_TOTAL.labels(outcome=outcome, decided_by=decided_by).inc()
    RUN_DURATION.observe(time.monotonic() - started)
    await publish_watch(watch_id, "run.completed", {
        "run_id": str(run_id), "outcome": outcome, "decided_by": decided_by, "reason": reason,
        "llm_called": bool(final.get("llm_called")), "alert_id": alert_id,
    })
    return RunSummary(run_id=str(run_id), outcome=outcome, decided_by=decided_by, reason=reason, alert_id=alert_id,
                      llm_called=bool(final.get("llm_called")), retry_after=retry_after,
                      failed=failed or outcome in ("error", "blocked"))


async def _persist(watch_id: uuid.UUID, run_id: uuid.UUID, final: EvalState, outcome: str, decided_by: str,
                   reason: str, started: float) -> None:
    now = datetime.now(UTC)
    diff_summary = None
    changed = [v for v in final.get("views") or [] if v.get("status") == "changed"]
    if changed:
        d = TextDiff(added=changed[0].get("diff_added", []), removed=changed[0].get("diff_removed", []))
        diff_summary = d.summary()
    async with session_scope() as s:
        run = await s.get(Run, run_id)
        assert run is not None
        run.status = "failed" if outcome == "error" else "completed"
        run.outcome = outcome
        run.decided_by = decided_by
        run.reason = reason[:2000]
        run.llm_called = bool(final.get("llm_called"))
        run.llm_tokens = int(final.get("llm_tokens") or 0)
        run.llm_cost_usd = float(final.get("llm_cost") or 0.0)
        run.confidence = final.get("confidence")
        run.diff_summary = diff_summary
        run.snapshot_ids = [uuid.UUID(v["snapshot_id"]) for v in final.get("views") or []]
        run.steps = final.get("steps") or []
        if final.get("source_errors"):
            run.error_code = final["source_errors"][0]["kind"]
            run.error_detail = final["source_errors"][0]["reason"][:1000]
        run.alert_id = uuid.UUID(final["alert_id"]) if final.get("alert_id") else None
        run.finished_at = now
        run.duration_ms = int((time.monotonic() - started) * 1000)

        w = await s.get(Watch, watch_id, with_for_update=True)
        if w is None:
            return
        if final.get("eval_state") is not None and not final.get("defer"):
            w.eval_state = final["eval_state"]
        if any(not v.get("selector_matched", True) for v in final.get("views") or [] if v.get("selector")):
            w.eval_state = {**(w.eval_state or {}), "selector_broken": True}
        learn = final.get("learn_noise") or []
        if learn:
            merged = list(dict.fromkeys(list(w.noise_signatures or []) + learn))[-NOISE_CAP:]
            w.noise_signatures = merged
        if not final.get("defer"):
            for v in final.get("views") or []:
                await s.execute(
                    pg_insert(WatchSourceState).values(
                        watch_id=watch_id, source_url=v["url"], view_hash=v.get("new_hash") or content_hash(v["text"]),
                        view_text=v["text"], items=v["links"][:500], snapshot_id=uuid.UUID(v["snapshot_id"]),
                    ).on_conflict_do_update(
                        index_elements=["watch_id", "source_url"],
                        set_={"view_hash": v.get("new_hash") or content_hash(v["text"]), "view_text": v["text"],
                              "items": v["links"][:500], "snapshot_id": uuid.UUID(v["snapshot_id"]), "updated_at": now},
                    )
                )
