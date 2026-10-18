"""Watch lifecycle: create, version, pause/resume, archive, fork, access control."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound, QuotaExceeded, ValidationFailed
from app.core.ids import slugify, uuid7
from app.models import Category, Check, Profile, Subscription, Watch, WatchVersion
from app.schemas.spec import WatchSpec
from app.services.plans import PlanInfo, assert_can_create_watch, clamp_interval
from app.workers.checks import ensure_check

VALID_VISIBILITY = {"private", "unlisted", "public"}


def enforce_plan_on_spec(spec: WatchSpec, plan: PlanInfo) -> WatchSpec:
    data = spec.model_dump()
    max_src = plan.limit("max_sources_per_watch")
    if len(spec.sources) > max_src:
        raise QuotaExceeded(f"Your plan allows up to {max_src} sources per watch.",
                            details={"metric": "max_sources_per_watch", "limit": max_src})
    if any(s.fetch_mode == "render" for s in spec.sources) and not plan.feature("js_render"):
        for s in data["sources"]:
            s["fetch_mode"] = "http"
    data["interval_seconds"] = clamp_interval(spec.interval_seconds, plan)
    return WatchSpec.model_validate(data)


async def _unique_slug(session: AsyncSession, title: str) -> str:
    base = slugify(title, 60)
    return f"{base}-{uuid7().hex[-6:]}"


async def create_watch(
    session: AsyncSession, *, owner: Profile, plan: PlanInfo, spec: WatchSpec, title: str, query_text: str,
    category: str | None = None, description: str | None = None, visibility: str = "private",
    created_by: str = "user", changelog: str | None = "Created", delivery_mode: str | None = None,
    tags: list[str] | None = None, forked_from: uuid.UUID | None = None, run_soon: bool = True,
) -> Watch:
    if owner.status != "active":
        raise Forbidden("Your account is not active")
    if visibility not in VALID_VISIBILITY:
        raise ValidationFailed("Invalid visibility")
    await assert_can_create_watch(session, owner, plan)
    spec = enforce_plan_on_spec(spec, plan)
    if category and await session.get(Category, category) is None:
        category = "other"
    title = " ".join(title.split())[:140] or "Untitled watch"
    w = Watch(
        id=uuid7(), owner_id=owner.id, title=title, description=description, query_text=query_text[:2000],
        category_slug=category or "other", kind=spec.kind, tags=[t[:40] for t in (tags or [])][:10],
        visibility="private", status="active", slug=await _unique_slug(session, title),
        default_delivery_mode=delivery_mode or owner.default_delivery_mode, auto_tune=owner.auto_tune,
        forked_from_id=forked_from, noise_signatures=[], eval_state={},
    )
    session.add(w)
    await session.flush()
    v = WatchVersion(watch_id=w.id, version=1, spec=spec.model_dump(mode="json"), spec_hash=spec.spec_hash(),
                     created_by=created_by, changelog=changelog)
    session.add(v)
    await session.flush()
    w.current_version_id = v.id
    session.add(Subscription(user_id=owner.id, watch_id=w.id, role="owner", delivery_mode=None))
    w.subscriber_count = 1
    await ensure_check(session, w.id, spec.interval_seconds, run_soon=run_soon)
    if visibility != "private":
        from app.services.community import request_visibility

        await request_visibility(session, w, owner, visibility, spec)
    return w


async def new_version(session: AsyncSession, w: Watch, spec: WatchSpec, *, plan: PlanInfo, created_by: str,
                      changelog: str, backtest: dict[str, Any] | None = None) -> WatchVersion:
    spec = enforce_plan_on_spec(spec, plan)
    cur = await session.get(WatchVersion, w.current_version_id) if w.current_version_id else None
    if cur is not None and cur.spec_hash == spec.spec_hash():
        return cur
    max_v = await session.scalar(select(func.max(WatchVersion.version)).where(WatchVersion.watch_id == w.id)) or 0
    v = WatchVersion(watch_id=w.id, version=max_v + 1, spec=spec.model_dump(mode="json"), spec_hash=spec.spec_hash(),
                     created_by=created_by, changelog=changelog[:2000], parent_version_id=w.current_version_id,
                     backtest=backtest)
    session.add(v)
    await session.flush()
    w.current_version_id = v.id
    w.kind = spec.kind
    old_sources = {s["url"] for s in (cur.spec.get("sources", []) if cur else [])}
    new_sources = {s.url for s in spec.sources}
    if old_sources != new_sources:
        # new pages: baseline again rather than alerting on everything already there
        w.eval_state = {}
    await ensure_check(session, w.id, spec.interval_seconds, run_soon=old_sources != new_sources)
    return v


async def get_watch_for_user(session: AsyncSession, watch_id: uuid.UUID, user: Profile | None, *,
                             write: bool = False, lock: bool = False) -> Watch:
    w = await session.get(Watch, watch_id, with_for_update=lock)
    if w is None or w.status == "archived" and not write:
        raise NotFound("Watch not found")
    is_owner = user is not None and w.owner_id == user.id
    admin = user is not None and user.role == "admin"
    if write:
        if not (is_owner or admin):
            raise NotFound("Watch not found") if w.visibility == "private" else Forbidden("Only the owner can do this")
        return w
    if is_owner or admin or w.visibility in ("public", "unlisted"):
        if w.visibility == "public" and w.moderation_status == "rejected" and not (is_owner or admin):
            raise NotFound("Watch not found")
        return w
    if user is not None:
        sub = await session.scalar(
            select(Subscription.id).where(Subscription.watch_id == w.id, Subscription.user_id == user.id)
        )
        if sub:
            return w
    raise NotFound("Watch not found")


async def set_status(session: AsyncSession, w: Watch, status: str, reason: str | None = None) -> None:
    w.status = status
    w.status_reason = reason
    enabled = status == "active"
    await session.execute(update(Check).where(Check.watch_id == w.id).values(enabled=enabled))
    if status == "archived":
        w.archived_at = datetime.now(UTC)
        if w.visibility != "private":
            w.visibility = "private"


async def run_now(session: AsyncSession, w: Watch) -> None:
    await session.execute(
        update(Check).where(Check.watch_id == w.id).values(
            next_run_at=datetime.now(UTC), priority=1, enabled=True, lease_until=None
        )
    )


async def fork_watch(session: AsyncSession, src: Watch, user: Profile, plan: PlanInfo) -> Watch:
    ver = await session.get(WatchVersion, src.current_version_id)
    if ver is None:
        raise NotFound("Watch has no definition")
    spec = WatchSpec.model_validate(ver.spec)
    return await create_watch(
        session, owner=user, plan=plan, spec=spec, title=f"{src.title} (my copy)"[:140], query_text=src.query_text,
        category=src.category_slug, description=src.description, created_by="user",
        changelog=f"Forked from '{src.title}'", forked_from=src.id, tags=list(src.tags or []),
    )
