"""Community watches: visibility & moderation, subscribe/unsubscribe, reports, explore/search, trending."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import prompts
from app.agents.schemas import ModerationOut
from app.core.config import get_settings
from app.core.db import after_commit, session_scope
from app.core.errors import Conflict, Forbidden, NotFound, QuotaExceeded, ValidationFailed
from app.core.logging import get_logger
from app.fetch.urls import domain_of
from app.llm.client import LLMError, get_llm
from app.models import (
    AbuseReport,
    AuditLog,
    Category,
    DomainPolicy,
    Profile,
    Subscription,
    Watch,
    WatchVersion,
)
from app.schemas.spec import WatchSpec
from app.services.plans import consume, count_subscriptions, plan_for
from app.workers.queue import Q_AGENTS, enqueue

log = get_logger(__name__)
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_SPAM_RE = re.compile(
    r"\b(earn\s+\$?\d+|work\s+from\s+home\s+earn|guaranteed\s+(returns|profit)|crypto\s+pump|betting\s+tips|"
    r"satta|matka|casino|xxx|escort|loan\s+approval\s+guaranteed|whatsapp\s+\+?\d{8,}|telegram\s+@\w+\s+for)\b", re.I)
PUBLIC_PER_DAY = 5


async def request_visibility(session: AsyncSession, w: Watch, owner: Profile, visibility: str,
                             spec: WatchSpec | None = None) -> None:
    if visibility == "private":
        w.visibility = "private"
        return
    if visibility not in ("unlisted", "public"):
        raise ValidationFailed("Invalid visibility")
    if not owner.email_verified:
        raise Forbidden("Verify your email before sharing watches with the community.")
    if visibility == "unlisted":
        w.visibility = "unlisted"
        return
    plan = await plan_for(session, owner)
    if not plan.feature("public_watches"):
        raise Forbidden("Your plan can't publish public watches.")
    await consume(session, owner.id, "public_publish", "day", PUBLIC_PER_DAY,
                  message="You can publish up to 5 public watches per day.")
    w.visibility = "public"
    if w.moderation_status != "approved":
        w.moderation_status = "pending"
    wid = w.id
    after_commit(session, lambda: enqueue("moderate_watch", str(wid), queue=Q_AGENTS, job_id=f"moderate:{wid}"))


def rule_moderation(title: str, description: str, condition: str, urls: list[str]) -> tuple[str, str] | None:
    blob = " ".join([title, description, condition, *urls])
    if _SPAM_RE.search(blob):
        return "reject", "Looks like spam or a scam"
    return None


async def moderate_watch(ctx: dict[str, Any] | None, watch_id: str) -> dict[str, Any]:
    wid = uuid.UUID(watch_id)
    async with session_scope() as s:
        w = await s.get(Watch, wid)
        if w is None or w.visibility != "public":
            return {"skipped": True}
        ver = await s.get(WatchVersion, w.current_version_id)
        spec = WatchSpec.model_validate(ver.spec)
        urls = [x.url for x in spec.sources]
        for u in urls:
            pol = await s.get(DomainPolicy, domain_of(u))
            if pol is not None and pol.denylisted:
                w.moderation_status, w.moderation_reason, w.visibility = "rejected", "Source site is not allowed", "private"
                return {"decision": "reject"}
        ruled = rule_moderation(w.title, w.description or "", spec.condition, urls)
        title, desc, owner_id = w.title, w.description or "", w.owner_id
    decision, reason = ruled if ruled else (None, "")
    if decision is None:
        try:
            res = await get_llm().structured(
                purpose="moderation", tier="fast", system=prompts.MODERATION_SYSTEM,
                user=prompts.moderation_user(title, desc, spec.condition, urls), schema=ModerationOut,
                max_tokens=300, user_id=owner_id,
            )
            decision, reason = res.data.decision, res.data.reason
        except LLMError:
            decision, reason = "review", "Automatic moderation unavailable; queued for review"
    async with session_scope() as s:
        w = await s.get(Watch, wid)
        if w is None:
            return {"skipped": True}
        if decision == "approve":
            w.moderation_status = "approved"
        elif decision == "reject":
            w.moderation_status = "rejected"
            w.visibility = "private"
        else:
            w.moderation_status = "pending"
        w.moderation_reason = reason[:500]
        s.add(AuditLog(actor_id=None, action=f"moderation.{decision}", target_type="watch", target_id=str(wid),
                       meta={"reason": reason[:300]}))
    if decision == "reject":
        from app.notify.dispatch import queue_system_notification

        await queue_system_notification(owner_id, key=f"moderation:{wid}", title="Your watch wasn't published",
                                        body=f"'{title}' can't be listed publicly: {reason}. It stays private for you.",
                                        link=f"/watches/{wid}")
    return {"decision": decision}


def is_listed(w: Watch) -> bool:
    return w.visibility == "public" and w.moderation_status == "approved" and w.status in ("active", "completed")


async def subscribe(session: AsyncSession, user: Profile, w: Watch, *, delivery_mode: str | None = None,
                    channels: list[str] | None = None) -> Subscription:
    if w.owner_id == user.id:
        raise Conflict("You own this watch")
    if not (is_listed(w) or w.visibility == "unlisted") or w.status == "archived":
        raise NotFound("Watch not found")
    if user.status != "active":
        raise Forbidden("Account not active")
    plan = await plan_for(session, user)
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"sub:{user.id}"})
    if await count_subscriptions(session, user.id) >= plan.limit("max_subscriptions"):
        raise QuotaExceeded(f"Your plan allows {plan.limit('max_subscriptions')} community subscriptions.",
                            details={"metric": "max_subscriptions", "limit": plan.limit("max_subscriptions")})
    if delivery_mode not in (None, "instant", "digest"):
        raise ValidationFailed("delivery_mode must be instant or digest")
    res = await session.execute(
        pg_insert(Subscription).values(user_id=user.id, watch_id=w.id, role="subscriber", delivery_mode=delivery_mode,
                                       channels=channels).on_conflict_do_nothing(index_elements=["user_id", "watch_id"])
        .returning(Subscription.id)
    )
    if res.scalar_one_or_none() is not None:
        await session.execute(update(Watch).where(Watch.id == w.id).values(subscriber_count=Watch.subscriber_count + 1))
    sub = (await session.execute(select(Subscription).where(Subscription.user_id == user.id,
                                                            Subscription.watch_id == w.id))).scalar_one()
    return sub


async def unsubscribe(session: AsyncSession, user: Profile, watch_id: uuid.UUID) -> bool:
    res = await session.execute(
        delete(Subscription).where(Subscription.user_id == user.id, Subscription.watch_id == watch_id,
                                   Subscription.role == "subscriber").returning(Subscription.id)
    )
    if res.scalar_one_or_none() is None:
        return False
    await session.execute(update(Watch).where(Watch.id == watch_id).values(
        subscriber_count=func.greatest(Watch.subscriber_count - 1, 0)))
    return True


async def report_watch(session: AsyncSession, user: Profile, w: Watch, reason: str, detail: str | None) -> dict[str, Any]:
    if reason not in ("spam", "scam", "harmful", "privacy", "broken", "other"):
        raise ValidationFailed("Invalid reason")
    res = await session.execute(
        pg_insert(AbuseReport).values(reporter_id=user.id, watch_id=w.id, reason=reason, detail=(detail or "")[:1000])
        .on_conflict_do_nothing(index_elements=["reporter_id", "watch_id"]).returning(AbuseReport.id)
    )
    if res.scalar_one_or_none() is None:
        return {"status": "already_reported"}
    w.report_count = (w.report_count or 0) + 1
    hidden = False
    if reason != "broken" and w.report_count >= get_settings().public_watch_report_threshold and w.visibility == "public":
        w.moderation_status = "pending"
        w.moderation_reason = f"Hidden after {w.report_count} reports; awaiting review"
        hidden = True
        session.add(AuditLog(actor_id=None, action="watch.auto_hidden", target_type="watch", target_id=str(w.id),
                             meta={"reports": w.report_count}))
    return {"status": "reported", "hidden": hidden}


# ------------------------------------------------------------------ explore
def _listed_filter() -> list[Any]:
    return [Watch.visibility == "public", Watch.moderation_status == "approved", Watch.status.in_(("active", "completed"))]


async def explore(session: AsyncSession, *, sort: str = "trending", category: str | None = None, q: str | None = None,
                  limit: int = 20, offset: int = 0) -> list[Watch]:
    stmt = select(Watch).where(*_listed_filter())
    if category:
        stmt = stmt.where(Watch.category_slug == category)
    if q:
        q = " ".join(q.split())[:100]
        tsq = func.websearch_to_tsquery("simple", q)
        stmt = stmt.where(or_(Watch.search_vector.op("@@")(tsq), Watch.title.op("%")(q), Watch.title.ilike(f"%{_like_escape(q)}%")))
        stmt = stmt.order_by(func.ts_rank(Watch.search_vector, tsq).desc(), func.similarity(Watch.title, q).desc(),
                             Watch.subscriber_count.desc())
    elif sort == "popular":
        stmt = stmt.order_by(Watch.subscriber_count.desc(), Watch.created_at.desc())
    elif sort == "new":
        stmt = stmt.order_by(Watch.created_at.desc())
    elif sort == "recently_fired":
        stmt = stmt.where(Watch.last_alert_at.is_not(None)).order_by(Watch.last_alert_at.desc())
    else:
        stmt = stmt.order_by(Watch.trending_score.desc(), Watch.subscriber_count.desc(), Watch.created_at.desc())
    stmt = stmt.limit(min(max(limit, 1), 50)).offset(max(offset, 0))
    return list((await session.execute(stmt)).scalars())


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def categories_with_counts(session: AsyncSession) -> list[dict[str, Any]]:
    counts = dict((await session.execute(
        select(Watch.category_slug, func.count()).where(*_listed_filter()).group_by(Watch.category_slug)
    )).all())
    cats = (await session.execute(select(Category).order_by(Category.sort))).scalars().all()
    return [{"slug": c.slug, "name": c.name, "description": c.description, "icon": c.icon,
             "watch_count": int(counts.get(c.slug, 0))} for c in cats]


COLLECTIONS = [
    {"slug": "exam-season", "title": "Exam & result alerts", "categories": ["exams-results", "admissions"]},
    {"slug": "placements", "title": "Jobs & placements", "categories": ["jobs", "placements"]},
    {"slug": "money", "title": "Scholarships & IPOs", "categories": ["scholarships", "ipo"]},
    {"slug": "deals", "title": "Price drops & restocks", "categories": ["price-drops", "restocks"]},
]


async def collections(session: AsyncSession, per: int = 6) -> list[dict[str, Any]]:
    out = []
    for c in COLLECTIONS:
        rows = (await session.execute(
            select(Watch).where(*_listed_filter(), Watch.category_slug.in_(c["categories"]))
            .order_by(Watch.trending_score.desc(), Watch.subscriber_count.desc()).limit(per)
        )).scalars().all()
        out.append({**c, "watches": rows})
    return out


async def recompute_trending(ctx: dict[str, Any] | None = None) -> int:
    """Trending = time-decayed new subscriptions (half-life ~2 days) + recent alert activity."""
    async with session_scope() as s:
        res = await s.execute(text(
            """
            UPDATE watches w SET
              trending_score = coalesce(t.sub_score, 0) + coalesce(t.alert_score, 0),
              popularity_score = ln(1 + w.subscriber_count) + coalesce(t.alert_score, 0) * 0.2
            FROM (
              SELECT w2.id,
                (SELECT sum(exp(-extract(epoch FROM now() - s.created_at) / 172800.0))
                   FROM subscriptions s WHERE s.watch_id = w2.id AND s.created_at > now() - interval '14 days'
                   AND s.role = 'subscriber') AS sub_score,
                (SELECT count(*) * 0.5 FROM alerts a WHERE a.watch_id = w2.id
                   AND a.created_at > now() - interval '7 days') AS alert_score
              FROM watches w2 WHERE w2.visibility = 'public'
            ) t
            WHERE w.id = t.id
            """
        ))
        return res.rowcount or 0


async def transfer_public_watches(session: AsyncSession, user_id: uuid.UUID) -> int:
    """On account deletion: public watches with other subscribers survive under the community account."""
    rows = (await session.execute(
        select(Watch).where(Watch.owner_id == user_id, Watch.visibility != "private", Watch.subscriber_count > 1)
    )).scalars().all()
    for w in rows:
        w.owner_id = SYSTEM_USER_ID
        await session.execute(delete(Subscription).where(Subscription.watch_id == w.id, Subscription.user_id == user_id))
        w.subscriber_count = max(0, w.subscriber_count - 1)
        await session.execute(pg_insert(Subscription).values(user_id=SYSTEM_USER_ID, watch_id=w.id, role="owner",
                                                             muted=True).on_conflict_do_nothing())
    # must hit the DB before any bulk delete of the old owner's watches runs
    await session.flush()
    return len(rows)


def recent_cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
