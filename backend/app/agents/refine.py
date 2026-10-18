"""Self-tuning: feedback -> proposed condition refinement -> backtest on labelled alerts -> apply or propose.

A refinement is applied automatically only when (a) the owner allows auto-tune, (b) their plan includes it and
(c) the backtest shows it keeps every alert the user found relevant while dropping at least one irrelevant one.
Every change becomes a new immutable watch version with a human-readable changelog.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agents import prompts
from app.agents.predicates import ViewContext, eval_all
from app.agents.schemas import BacktestJudgeOut, RefineOut
from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.fetch.diff import TextDiff
from app.llm.client import LLMError, get_llm
from app.models import Alert, Feedback, Profile, RefinementProposal, Watch, WatchVersion
from app.realtime.events import publish_user, publish_watch
from app.schemas.spec import Predicate, WatchSpec
from app.services.plans import effective_plan_id, get_plan
from app.workers.queue import Q_AGENTS, enqueue

log = get_logger(__name__)
MIN_IRRELEVANT = 2
MAX_LABELLED = 20


async def maybe_trigger_refinement(watch_id: uuid.UUID, *, force: bool = False) -> bool:
    async with session_scope() as s:
        rows = (await s.execute(select(Feedback.relevant, Feedback.reason).where(Feedback.watch_id == watch_id))).all()
    irrelevant = [r for r in rows if not r.relevant]
    with_reason = any(r.reason for r in irrelevant)
    if not force and not (len(irrelevant) >= MIN_IRRELEVANT or (irrelevant and with_reason)):
        return False
    # debounce: one refinement per watch per 30 minutes
    if not await get_redis().set(f"refine:debounce:{watch_id}", "1", nx=True, ex=1800) and not force:
        return False
    await enqueue("refine_watch", str(watch_id), queue=Q_AGENTS, job_id=f"refine:{watch_id}:{uuid.uuid4().hex[:6]}")
    return True


def _alert_text(a: Alert) -> str:
    facts = "; ".join(f"{k}: {v}" for k, v in (a.key_facts or {}).items())
    return f"{a.title}\n{a.summary}\nEvidence: {a.evidence or ''}\n{facts}\n{(a.context_excerpt or '')[:1500]}"


async def _labelled(session: Any, w: Watch) -> list[tuple[Alert, bool, list[str]]]:
    rows = (await session.execute(
        select(Feedback, Alert).join(Alert, Alert.id == Feedback.alert_id).where(Feedback.watch_id == w.id)
        .order_by(Alert.created_at.desc()).limit(200)
    )).all()
    per: dict[uuid.UUID, dict[str, Any]] = {}
    for fb, alert in rows:
        e = per.setdefault(alert.id, {"alert": alert, "yes": 0, "no": 0, "owner": None, "notes": []})
        if fb.user_id == w.owner_id:
            e["owner"] = fb.relevant
        if fb.relevant:
            e["yes"] += 1
        else:
            e["no"] += 1
        if fb.reason:
            e["notes"].append(fb.reason[:200])
    out = []
    for e in list(per.values())[:MAX_LABELLED]:
        label = e["owner"] if e["owner"] is not None else e["yes"] >= e["no"]
        out.append((e["alert"], bool(label), e["notes"]))
    return out


async def _backtest(spec: WatchSpec, labelled: list[tuple[Alert, bool, list[str]]], owner_id: uuid.UUID,
                    plan_id: str) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    details = []
    for alert, relevant, _ in labelled:
        text_ = _alert_text(alert)
        # "added"-scoped rules look only at what triggered the alert, not surrounding/removed page lines
        trigger = [alert.title, alert.summary, alert.evidence or "",
                   *(f"{k}: {v}" for k, v in (alert.key_facts or {}).items())]
        ctx = ViewContext(text=text_, diff=TextDiff(added=[t for t in trigger if t], removed=[]),
                          new_items=[{"text": alert.evidence or alert.title, "href": alert.source_url}],
                          structured={}, changed=True)
        predicted = eval_all(spec.predicates, ctx).passed if spec.predicates else True
        if predicted and spec.predicate_mode != "decide":
            try:
                res = await get_llm().structured(
                    purpose="backtest", tier="smart", system=prompts.BACKTEST_SYSTEM,
                    user=prompts.backtest_user(spec.condition, text_), schema=BacktestJudgeOut, max_tokens=200,
                    user_id=owner_id, plan_id=plan_id,
                )
                predicted = res.data.condition_met and res.data.confidence >= 0.5
            except LLMError:
                return {"ok": False, "error": "backtest_llm_unavailable"}
        if predicted and relevant:
            tp += 1
        elif predicted and not relevant:
            fp += 1
        elif not predicted and relevant:
            fn += 1
        else:
            tn += 1
        details.append({"alert_id": str(alert.id), "title": alert.title[:120], "relevant": relevant,
                        "would_alert": predicted})
    total_rel = tp + fn
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / total_rel if total_rel else 1.0
    return {"ok": True, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 3),
            "recall": round(recall, 3), "cases": details}


def _merge_spec(spec: WatchSpec, r: RefineOut) -> tuple[WatchSpec, list[str]]:
    data = spec.model_dump()
    changes = []
    if r.new_condition and r.new_condition.strip() != spec.condition:
        data["condition"] = r.new_condition.strip()[:600]
        changes.append(f"Condition: “{spec.condition}” → “{data['condition']}”")
    if r.add_negative_examples:
        data["negative_examples"] = list(dict.fromkeys(spec.negative_examples + r.add_negative_examples))[-10:]
        changes.append(f"Learned {len(r.add_negative_examples)} example(s) of what NOT to alert on")
    if r.add_positive_examples:
        data["positive_examples"] = list(dict.fromkeys(spec.positive_examples + r.add_positive_examples))[-10:]
        changes.append(f"Learned {len(r.add_positive_examples)} example(s) of good alerts")
    preds = list(data["predicates"])
    if r.add_exclude_terms:
        try:
            preds.append(Predicate(type="not_contains", values=r.add_exclude_terms[:8], scope="added").model_dump())
            changes.append("Ignore changes mentioning: " + ", ".join(r.add_exclude_terms[:8]))
        except ValueError:
            pass
    if r.add_require_terms:
        try:
            preds.append(Predicate(type="contains_any", values=r.add_require_terms[:8], scope="added").model_dump())
            changes.append("Only consider changes mentioning: " + ", ".join(r.add_require_terms[:8]))
        except ValueError:
            pass
    if len(preds) > 8:
        preds = preds[-8:]
    data["predicates"] = preds
    if preds and data["predicate_mode"] == "none":
        data["predicate_mode"] = "prefilter"
    return WatchSpec.model_validate(data), changes


async def refine_watch(ctx: dict[str, Any] | None, watch_id: str) -> dict[str, Any]:
    wid = uuid.UUID(watch_id)
    async with session_scope() as s:
        w = await s.get(Watch, wid)
        if w is None or w.current_version_id is None:
            return {"status": "missing"}
        ver = await s.get(WatchVersion, w.current_version_id)
        owner = await s.get(Profile, w.owner_id)
        plan = await get_plan(s, effective_plan_id(owner))
        spec = WatchSpec.model_validate(ver.spec)
        labelled = await _labelled(s, w)
        auto = bool(w.auto_tune and owner.auto_tune and plan.feature("auto_tune"))
        owner_id, version_id, title = owner.id, ver.id, w.title
    if not any(not rel for _, rel, _ in labelled):
        return {"status": "nothing_to_learn"}
    relevant = [f"{a.title}: {a.summary[:200]}" for a, rel, _ in labelled if rel]
    irrelevant = [f"{a.title}: {a.summary[:200]}" for a, rel, _ in labelled if not rel]
    notes = [n for _, _, ns in labelled for n in ns][:10]
    try:
        res = await get_llm().structured(purpose="refine", tier="smart", system=prompts.REFINE_SYSTEM,
                                         user=prompts.refine_user(spec.condition, relevant, irrelevant, notes),
                                         schema=RefineOut, max_tokens=900, user_id=owner_id, plan_id=plan.id)
    except LLMError as e:
        return {"status": "llm_unavailable", "error": e.code}
    try:
        new_spec, changes = _merge_spec(spec, res.data)
    except ValueError as e:
        return {"status": "invalid_proposal", "error": str(e)[:200]}
    if not changes:
        return {"status": "no_change"}
    old_bt = await _backtest(spec, labelled, owner_id, plan.id)
    new_bt = await _backtest(new_spec, labelled, owner_id, plan.id)
    if not new_bt.get("ok") or not old_bt.get("ok"):
        return {"status": "backtest_failed"}
    n_rel = new_bt["tp"] + new_bt["fn"]
    keeps_relevant = new_bt["fn"] == 0 if n_rel <= 10 else new_bt["recall"] >= 0.9
    improves = new_bt["precision"] > old_bt["precision"] or new_bt["fp"] < old_bt["fp"]
    backtest = {"before": {k: old_bt[k] for k in ("precision", "recall", "tp", "fp", "fn")},
                "after": {k: new_bt[k] for k in ("precision", "recall", "tp", "fp", "fn")},
                "cases": new_bt["cases"], "accepted": keeps_relevant and improves}
    applied_version = None
    async with session_scope() as s:
        w = await s.get(Watch, wid, with_for_update=True)
        if w is None or w.current_version_id != version_id:
            return {"status": "stale"}
        # supersede older pending proposals
        for old in (await s.execute(select(RefinementProposal).where(
                RefinementProposal.watch_id == wid, RefinementProposal.status == "pending"))).scalars():
            old.status = "superseded"
        prop = RefinementProposal(watch_id=wid, from_version_id=version_id, proposed_spec=new_spec.model_dump(mode="json"),
                                  rationale=res.data.rationale, changes=changes, backtest=backtest, status="pending")
        s.add(prop)
        await s.flush()
        if backtest["accepted"] and auto:
            from app.services.watches import new_version

            v = await new_version(s, w, new_spec, plan=plan, created_by="refinement",
                                  changelog="Auto-tuned from your feedback: " + "; ".join(changes), backtest=backtest)
            prop.status = "applied"
            prop.applied_version_id = v.id
            applied_version = v.version
        prop_id = prop.id
    if applied_version is not None:
        await publish_watch(wid, "watch.refined", {"version": applied_version, "changes": changes})
        from app.notify.dispatch import queue_system_notification

        await queue_system_notification(owner_id, key=f"refined:{wid}:{applied_version}",
                                        title=f"'{title[:60]}' got smarter",
                                        body="Based on your feedback I tuned this watch:\n- " + "\n- ".join(changes),
                                        link=f"/watches/{wid}/versions")
        return {"status": "applied", "version": applied_version, "backtest": backtest}
    if backtest["accepted"]:
        await publish_user(owner_id, "refinement.proposed", {"watch_id": watch_id, "proposal_id": str(prop_id),
                                                             "changes": changes})
        return {"status": "proposed", "proposal_id": str(prop_id), "backtest": backtest}
    async with session_scope() as s:
        p = await s.get(RefinementProposal, prop_id)
        if p is not None:
            p.status = "rejected"
    return {"status": "rejected_by_backtest", "backtest": backtest}
