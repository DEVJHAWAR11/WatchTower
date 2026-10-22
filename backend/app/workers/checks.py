"""Check execution job + next-run scheduling (jitter, exponential backoff, failure escalation)."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.agents.evaluate import COMMUNITY_SUBSCRIBERS, run_evaluation
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import QuotaExceeded
from app.core.logging import get_logger
from app.models import Check, Profile, Watch, WatchVersion
from app.realtime.events import publish_watch
from app.services.plans import consume, next_month_start, plan_for
from app.workers.queue import Q_AGENTS, enqueue

log = get_logger(__name__)

RUNNABLE_STATUSES = {"active", "error"}  # errored watches keep probing (daily) so they can self-heal


def next_time(interval: int, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    jitter = interval * 0.1
    return now + timedelta(seconds=max(60, interval + random.uniform(-jitter, jitter)))


def backoff_time(interval: int, failures: int, retry_after: int | None, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    cap = get_settings().check_max_backoff_seconds
    base = min(cap, max(300, interval) * (2 ** min(failures - 1, 8)))
    if retry_after:
        base = max(base, min(retry_after, cap))
    return now + timedelta(seconds=base * random.uniform(0.9, 1.1))


async def run_check(ctx: dict[str, Any] | None, check_id: str, lease_token: str) -> dict[str, Any]:
    cid = uuid.UUID(check_id)
    async with session_scope() as s:
        chk = await s.get(Check, cid)
        if chk is None or chk.lease_token != lease_token:
            return {"skipped": "lease_lost"}
        w = await s.get(Watch, chk.watch_id)
        if w is None or w.status not in RUNNABLE_STATUSES:
            chk.enabled = False
            chk.lease_until = None
            chk.lease_token = None
            return {"skipped": "watch_not_active"}
        ver = await s.get(WatchVersion, w.current_version_id) if w.current_version_id else None
        if ver is not None and ver.spec.get("expires_at"):
            exp = datetime.fromisoformat(str(ver.spec["expires_at"]).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                w.status = "expired"
                w.status_reason = "The watch passed its end date."
                chk.enabled = False
                chk.lease_until = None
                chk.lease_token = None
                return {"skipped": "expired"}
        trigger = "manual" if chk.priority > 0 else "schedule"
        community = w.visibility == "public" and w.subscriber_count >= COMMUNITY_SUBSCRIBERS
        owner = None if community or trigger == "manual" else await s.get(Profile, w.owner_id)
        if owner is not None:
            # Scheduled checks count against the owner's monthly allowance; shared community watches are free to run.
            plan = await plan_for(s, owner)
            try:
                await consume(s, owner.id, "checks", "month", plan.limit("checks_per_month"))
            except QuotaExceeded:
                chk.next_run_at = next_month_start() + timedelta(seconds=random.uniform(0, 6 * 3600))
                chk.lease_until = None
                chk.lease_token = None
                return {"skipped": "checks_cap"}
        watch_id = w.id

    try:
        summary = await run_evaluation(watch_id, trigger=trigger)
    except LookupError:
        async with session_scope() as s:
            await s.execute(update(Check).where(Check.id == cid).values(enabled=False, lease_until=None, lease_token=None))
        return {"skipped": "no_version"}

    escalate = False
    async with session_scope() as s:
        chk = await s.get(Check, cid, with_for_update=True)
        w = await s.get(Watch, watch_id, with_for_update=True)
        if chk is None or w is None:
            return dict(summary)
        now = datetime.now(UTC)
        outcome = summary["outcome"]
        if outcome in ("error", "blocked"):
            chk.consecutive_failures = (chk.consecutive_failures or 0) + 1
            chk.next_run_at = backoff_time(chk.interval_seconds, chk.consecutive_failures, summary["retry_after"])
            if chk.consecutive_failures >= get_settings().check_failure_threshold and w.status == "active":
                w.status = "error"
                w.status_reason = f"Paused after {chk.consecutive_failures} failed checks: {summary['reason'][:300]}"
                escalate = True
                # keep probing slowly so the watch can self-heal
                chk.next_run_at = now + timedelta(seconds=get_settings().check_max_backoff_seconds)
        elif outcome == "deferred":
            chk.next_run_at = now + timedelta(seconds=max(120, min(summary["retry_after"] or 900, 6 * 3600)))
        else:
            chk.consecutive_failures = 0
            chk.next_run_at = next_time(chk.interval_seconds, now=now)
        if w.status in ("completed", "expired", "archived", "paused"):
            chk.enabled = False
        chk.last_run_at = now
        chk.last_run_id = uuid.UUID(summary["run_id"])
        chk.lease_until = None
        chk.lease_token = None
        chk.priority = 0
        next_run = chk.next_run_at
        owner_id = w.owner_id
        title = w.title
        status = w.status
    await publish_watch(watch_id, "watch.scheduled", {"next_run_at": next_run.isoformat(), "status": status})
    if summary["alert_id"]:
        await enqueue("act_on_alert", summary["alert_id"], queue=Q_AGENTS, job_id=f"act:{summary['alert_id']}")
    if escalate:
        from app.notify.dispatch import queue_system_notification

        await queue_system_notification(
            owner_id, key=f"watch-error:{watch_id}:{now.date()}", title=f"Watch paused: {title[:80]}",
            body=f"We couldn't check this watch {get_settings().check_failure_threshold} times in a row. "
                 f"Reason: {summary['reason'][:300]} We'll keep retrying daily; you can edit its source or resume it.",
            link=f"/watches/{watch_id}",
        )
    # Self-heal: a watch in error that just succeeded goes back to active.
    if outcome_ok(summary["outcome"]) and status == "error":
        async with session_scope() as s:
            await s.execute(
                update(Watch).where(Watch.id == watch_id, Watch.status == "error")
                .values(status="active", status_reason=None)
            )
            await s.execute(update(Check).where(Check.watch_id == watch_id).values(enabled=True))
    return dict(summary)


def outcome_ok(outcome: str) -> bool:
    return outcome in ("matched", "no_match", "duplicate", "skipped_unchanged", "baseline")


async def ensure_check(session: Any, watch_id: uuid.UUID, interval: int, *, run_soon: bool = True) -> Check:
    chk = (await session.execute(select(Check).where(Check.watch_id == watch_id))).scalar_one_or_none()
    first = datetime.now(UTC) + (timedelta(seconds=5) if run_soon else timedelta(seconds=interval))
    if chk is None:
        chk = Check(watch_id=watch_id, interval_seconds=interval, enabled=True, next_run_at=first)
        session.add(chk)
    else:
        chk.interval_seconds = interval
        chk.enabled = True
        if run_soon:
            chk.next_run_at = min(chk.next_run_at, first) if chk.next_run_at else first
    return chk
