"""Community discovery: trending, popular, new, search, categories, India-first collections."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DB, OptionalUser, rate_limit
from app.api.v1.common import owner_out
from app.core.errors import NotFound
from app.models import Alert, Watch
from app.schemas.api import PublicWatchOut
from app.services import community

router = APIRouter(prefix="/explore", tags=["explore"])


async def _cards(session: Any, rows: list[Watch]) -> list[dict[str, Any]]:
    out = []
    for w in rows:
        card = PublicWatchOut.model_validate(w).model_dump(mode="json")
        card["owner"] = (await owner_out(session, w.owner_id)).model_dump()
        out.append(card)
    return out


@router.get("", dependencies=[Depends(rate_limit("explore", 120, 60, per="ip"))])
async def explore(session: DB, sort: str = Query("trending", pattern="^(trending|popular|new|recently_fired)$"),
                  category: str | None = Query(None, max_length=48), q: str | None = Query(None, max_length=100),
                  limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=1000)) -> dict[str, Any]:
    rows = await community.explore(session, sort=sort, category=category, q=q, limit=limit, offset=offset)
    return {"items": await _cards(session, rows), "next_offset": offset + limit if len(rows) == limit else None}


@router.get("/categories")
async def categories(session: DB) -> list[dict[str, Any]]:
    return await community.categories_with_counts(session)


@router.get("/collections")
async def collections(session: DB) -> list[dict[str, Any]]:
    cols = await community.collections(session)
    return [{**{k: v for k, v in c.items() if k != "watches"}, "watches": await _cards(session, c["watches"])}
            for c in cols]


@router.get("/watches/{slug}")
async def by_slug(slug: str, session: DB, user: OptionalUser) -> dict[str, Any]:
    w = (await session.execute(select(Watch).where(Watch.slug == slug[:80]))).scalar_one_or_none()
    if w is None or not (community.is_listed(w) or w.visibility == "unlisted"):
        raise NotFound("Watch not found")
    recent = (await session.execute(select(Alert).where(Alert.watch_id == w.id).order_by(Alert.created_at.desc())
                                    .limit(5))).scalars().all()
    card = (await _cards(session, [w]))[0]
    card["recent_alerts"] = [{"id": str(a.id), "title": a.title, "summary": a.summary, "source_url": a.source_url,
                              "created_at": a.created_at.isoformat()} for a in recent]
    card["is_owner"] = user is not None and user.id == w.owner_id
    return card
