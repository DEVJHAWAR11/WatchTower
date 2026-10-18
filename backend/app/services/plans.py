"""Plans, limits and atomic quota consumption. Limits are data (plans table), cached briefly in-process."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceeded
from app.models import Plan, Profile, Subscription, Watch

_CACHE: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
_TTL = 60.0

DEFAULT_LIMITS = {
    "max_watches": 5, "max_subscriptions": 25, "min_interval_seconds": 21600, "acts_per_month": 20,
    "intake_per_day": 10, "run_now_per_day": 3, "llm_tokens_per_day": 150000, "retention_days": 30,
    "max_sources_per_watch": 2, "max_alerts_per_hour": 6,
}


@dataclass
class PlanInfo:
    id: str
    limits: dict[str, Any]
    features: dict[str, Any]

    def limit(self, key: str) -> int:
        return int(self.limits.get(key, DEFAULT_LIMITS.get(key, 0)))

    def feature(self, key: str) -> Any:
        return self.features.get(key)


def effective_plan_id(profile: Profile) -> str:
    if profile.plan_id != "free" and profile.plan_expires_at and profile.plan_expires_at < datetime.now(UTC):
        return "free"
    return profile.plan_id or "free"


async def get_plan(session: AsyncSession, plan_id: str) -> PlanInfo:
    hit = _CACHE.get(plan_id)
    if hit and time.monotonic() - hit[0] < _TTL:
        return PlanInfo(plan_id, hit[1], hit[2])
    plan = await session.get(Plan, plan_id)
    if plan is None:
        plan = await session.get(Plan, "free")
    limits = dict(plan.limits) if plan else dict(DEFAULT_LIMITS)
    features = dict(plan.features) if plan else {}
    _CACHE[plan_id] = (time.monotonic(), limits, features)
    return PlanInfo(plan_id, limits, features)


def invalidate_plan_cache() -> None:
    _CACHE.clear()


async def plan_for(session: AsyncSession, profile: Profile) -> PlanInfo:
    return await get_plan(session, effective_plan_id(profile))


def period_start(period: str, today: date | None = None) -> date:
    d = today or datetime.now(UTC).date()
    return d.replace(day=1) if period == "month" else d


async def consume(session: AsyncSession, user_id: uuid.UUID, metric: str, period: str, limit: int,
                  amount: int = 1, *, message: str | None = None) -> int:
    """Atomically add `amount` if it keeps the counter within `limit`; raise QuotaExceeded otherwise."""
    if amount > limit:
        raise QuotaExceeded(message or f"Plan limit reached for {metric}", details={"metric": metric, "limit": limit})
    row = (
        await session.execute(
            text(
                """
                INSERT INTO usage_counters (user_id, metric, period, period_start, value)
                VALUES (:uid, :metric, :period, :ps, :amt)
                ON CONFLICT (user_id, metric, period, period_start)
                DO UPDATE SET value = usage_counters.value + :amt
                WHERE usage_counters.value + :amt <= :limit
                RETURNING value
                """
            ),
            {"uid": user_id, "metric": metric, "period": period, "ps": period_start(period), "amt": amount,
             "limit": limit},
        )
    ).first()
    if row is None:
        raise QuotaExceeded(
            message or f"Plan limit reached for {metric}", details={"metric": metric, "limit": limit, "period": period}
        )
    return int(row[0])


async def refund(session: AsyncSession, user_id: uuid.UUID, metric: str, period: str, amount: int = 1) -> None:
    await session.execute(
        text(
            "UPDATE usage_counters SET value = GREATEST(value - :amt, 0) "
            "WHERE user_id = :uid AND metric = :metric AND period = :period AND period_start = :ps"
        ),
        {"uid": user_id, "metric": metric, "period": period, "ps": period_start(period), "amt": amount},
    )


async def usage_value(session: AsyncSession, user_id: uuid.UUID, metric: str, period: str) -> int:
    row = (
        await session.execute(
            text(
                "SELECT value FROM usage_counters WHERE user_id=:uid AND metric=:m AND period=:p AND period_start=:ps"
            ),
            {"uid": user_id, "m": metric, "p": period, "ps": period_start(period)},
        )
    ).first()
    return int(row[0]) if row else 0


async def count_owned_watches(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Watch).where(
                Watch.owner_id == user_id, Watch.status.notin_(("archived",))
            )
        )
        or 0
    )


async def count_subscriptions(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Subscription).where(
                Subscription.user_id == user_id, Subscription.role == "subscriber"
            )
        )
        or 0
    )


async def assert_can_create_watch(session: AsyncSession, profile: Profile, plan: PlanInfo) -> None:
    # Serialise concurrent creates for the same user so two requests can't both pass the count check.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"watch-create:{profile.id}"})
    n = await count_owned_watches(session, profile.id)
    if n >= plan.limit("max_watches"):
        raise QuotaExceeded(
            f"Your {plan.id} plan allows {plan.limit('max_watches')} active watches. Archive one or upgrade.",
            details={"metric": "max_watches", "limit": plan.limit("max_watches")},
        )


def clamp_interval(seconds: int, plan: PlanInfo) -> int:
    return max(int(seconds), plan.limit("min_interval_seconds"))
