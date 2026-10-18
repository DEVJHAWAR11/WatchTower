"""FastAPI dependencies: auth (Supabase JWT or personal API token), profile bootstrap, rate limits, idempotency."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, decode_supabase_jwt, principal_from_claims
from app.core.crypto import hash_token
from app.core.db import get_db
from app.core.errors import Forbidden, RateLimited, Unauthorized
from app.core.redis import get_redis, sliding_window_allow
from app.models import ApiToken, Profile

DB = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "0.0.0.0"  # noqa: S104 - only used as a rate-limit key


async def _principal_from_api_token(session: AsyncSession, token: str) -> Principal:
    row = (await session.execute(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or (row.expires_at and row.expires_at < now):
        raise Unauthorized("Invalid API token")
    # throttle last_used_at writes
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 300:
        await session.execute(update(ApiToken).where(ApiToken.id == row.id).values(last_used_at=now))
    return Principal(user_id=row.user_id, email=None, email_verified=False, role="user", via="api_token",
                     scopes=list(row.scopes or []))


async def get_principal(session: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token or len(token) > 8192:
        raise Unauthorized("Invalid token")
    if token.startswith("wt_"):
        return await _principal_from_api_token(session, token)
    claims = await decode_supabase_jwt(token)
    return principal_from_claims(claims)


async def get_optional_principal(session: DB, authorization: Annotated[str | None, Header()] = None) -> Principal | None:
    if not authorization:
        return None
    return await get_principal(session, authorization)


async def ensure_profile(session: AsyncSession, p: Principal) -> Profile:
    prof = await session.get(Profile, p.user_id)
    now = datetime.now(UTC)
    if prof is None:
        if p.via != "jwt":
            raise Unauthorized("Unknown user")
        await session.execute(pg_insert(Profile).values(
            id=p.user_id, email=(p.email or "").lower() or None, email_verified=p.email_verified, plan_id="free",
            default_channels=["email"], last_seen_at=now, role="admin" if p.is_admin else "user",
        ).on_conflict_do_nothing(index_elements=["id"]))
        prof = await session.get(Profile, p.user_id)
        assert prof is not None
        return prof
    if prof.status == "deleted":
        raise Unauthorized("This account has been deleted")
    if prof.status == "suspended":
        raise Forbidden(f"Account suspended{': ' + prof.status_reason if prof.status_reason else ''}")
    if p.via == "jwt":
        email = (p.email or "").lower() or None
        changed = False
        if email and prof.email != email:
            prof.email = email
            changed = True
        if p.email_verified and not prof.email_verified:
            prof.email_verified = True
            changed = True
        # Supabase app_metadata is the source of truth for the admin role (both grant and revoke).
        want_role = "admin" if p.is_admin else "user"
        if prof.role != want_role:
            prof.role = want_role
            changed = True
        if changed or prof.last_seen_at is None or (now - prof.last_seen_at).total_seconds() > 300:
            prof.last_seen_at = now
    return prof


async def current_user(session: DB, principal: Annotated[Principal, Depends(get_principal)]) -> Profile:
    prof = await ensure_profile(session, principal)
    if principal.via == "api_token":
        from app.services.plans import plan_for

        plan = await plan_for(session, prof)
        if not plan.feature("api_tokens"):
            raise Forbidden("API tokens require the Pro plan")
    return prof


async def optional_user(session: DB, principal: Annotated[Principal | None, Depends(get_optional_principal)]) -> Profile | None:
    if principal is None:
        return None
    return await ensure_profile(session, principal)


CurrentUser = Annotated[Profile, Depends(current_user)]
OptionalUser = Annotated[Profile | None, Depends(optional_user)]


async def require_admin(user: CurrentUser) -> Profile:
    if user.role != "admin":
        raise Forbidden("Admin only")
    return user


AdminUser = Annotated[Profile, Depends(require_admin)]


def rate_limit(name: str, limit: int, window_seconds: int, *, per: str = "user") -> Callable[..., Awaitable[None]]:
    """Dependency factory. per='user' needs auth; per='ip' works for anonymous endpoints."""

    async def _dep(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
        if per == "ip":
            ident = f"ip:{client_ip(request)}"
        else:
            ident = f"tok:{hash_token(authorization or client_ip(request))[:24]}"
        ok, retry = await sliding_window_allow(f"rl:{name}:{ident}", limit, window_seconds)
        if not ok:
            raise RateLimited(f"Too many requests. Try again in {retry}s.", retry_after=retry)

    return _dep


class Idempotency:
    """Opt-in via `Idempotency-Key` header on POSTs that create things. Replays the first response for 24h."""

    def __init__(self, request: Request, user: Profile, key: str | None):
        self.key = None
        if key:
            k = key.strip()[:128]
            self.key = f"idem:{user.id}:{request.url.path}:{k}"

    async def cached(self) -> Any | None:
        if not self.key:
            return None
        raw = await get_redis().get(self.key)
        return json.loads(raw) if raw else None

    async def store(self, body: Any) -> None:
        if self.key:
            await get_redis().set(self.key, json.dumps(body, default=str), ex=24 * 3600)


async def idempotency(request: Request, user: CurrentUser,
                      idempotency_key: Annotated[str | None, Header()] = None) -> Idempotency:
    return Idempotency(request, user, idempotency_key)


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        from app.core.errors import NotFound

        raise NotFound("Not found") from e
