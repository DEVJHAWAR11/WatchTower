"""Server-Sent Events: real-time updates for the signed-in user and any watches they are viewing.

Auth: `Authorization: Bearer` (fetch-based SSE clients) or `?ticket=` from POST /v1/stream/ticket (native
EventSource can't send headers). Reconnects resume exactly where they left off via Last-Event-ID, which encodes the
position in every subscribed Redis stream.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import anyio
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import DB, CurrentUser, OptionalUser
from app.core.crypto import sign_payload, verify_payload
from app.core.db import session_scope
from app.core.errors import RateLimited, Unauthorized
from app.core.redis import get_redis
from app.models import Profile
from app.realtime.events import user_stream, watch_stream
from app.services.watches import get_watch_for_user

router = APIRouter(prefix="/stream", tags=["realtime"])
MAX_STREAMS_PER_USER = 6
HEARTBEAT = 15
# How long one XREAD blocks before the loop re-checks the connection and whether a ping is due.
POLL = 2
# Each open stream holds a lease it renews every heartbeat. A connection that vanished without a clean close
# (proxy hiccup, killed process) stops renewing and frees its slot after LEASE seconds instead of an hour.
LEASE = HEARTBEAT * 3


def _encode_pos(pos: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(pos, separators=(",", ":")).encode()).decode().rstrip("=")


def _order_key(entry_id: str, fields: dict[str, str]) -> tuple[int, int, int]:
    """Global publish sequence first (set atomically on publish), stream id as a fallback."""
    ms, _, seq = entry_id.partition("-")
    gseq = fields.get("s", "")
    return (int(gseq) if gseq.isdigit() else 0), int(ms), int(seq or 0)


def _decode_pos(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except ValueError:
        return {}


@router.post("/ticket")
async def ticket(user: CurrentUser) -> dict[str, object]:
    return {"ticket": sign_payload({"u": str(user.id)}, "sse", ttl_seconds=60), "expires_in": 60}


@router.get("")
async def stream(
    request: Request, session: DB, user: OptionalUser,
    watch: Annotated[list[uuid.UUID] | None, Query(max_length=10)] = None,
    ticket: str | None = None,
    last_event_id: Annotated[str | None, Header()] = None,
    since: str | None = Query(None, description="Alternative to Last-Event-ID header"),
) -> StreamingResponse:
    if user is None and ticket:
        data = verify_payload(ticket, "sse")
        if data:
            async with session_scope() as s:
                user = await s.get(Profile, uuid.UUID(data["u"]))
    if user is None or user.status != "active":
        raise Unauthorized("Sign in to stream updates")
    streams = [user_stream(user.id)]
    for wid in watch or []:
        await get_watch_for_user(session, wid, user)  # access check
        streams.append(watch_stream(wid))
    await session.commit()
    r = get_redis()
    leases = f"sse:leases:{user.id}"
    conn_id = uuid.uuid4().hex
    now = time.time()
    async with r.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(leases, "-inf", now)
        pipe.zadd(leases, {conn_id: now + LEASE})
        pipe.zcard(leases)
        pipe.expire(leases, LEASE * 2)
        _, _, n, _ = await pipe.execute()
    if n > MAX_STREAMS_PER_USER:
        await r.zrem(leases, conn_id)
        raise RateLimited("Too many open live connections", retry_after=10)
    pos = _decode_pos(last_event_id or since)
    positions = {s: pos.get(s, "$") for s in streams}
    # "$" means "only new events": resolve to the current last id so nothing slips between XREAD calls
    for s_key, p in list(positions.items()):
        if p == "$":
            last = await r.xrevrange(s_key, count=1)
            positions[s_key] = last[0][0] if last else "0-0"

    async def gen() -> AsyncIterator[bytes]:
        try:
            yield b"retry: 3000\n\n"
            yield f"event: ready\ndata: {json.dumps({'streams': len(streams)})}\nid: {_encode_pos(positions)}\n\n".encode()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    res = await r.xread(positions, block=POLL * 1000, count=100)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(1)
                    continue
                await r.zadd(leases, {conn_id: time.time() + LEASE})
                if not res:
                    yield b": ping\n\n"
                    continue
                # XREAD groups results per stream; merge by entry id (same Redis clock) so the client sees
                # events in the order they actually happened across the user and watch streams.
                merged = sorted(
                    ((_order_key(entry_id, fields), s_key, entry_id, fields)
                     for s_key, entries in res for entry_id, fields in entries),
                    key=lambda t: t[0],
                )
                for _, s_key, entry_id, fields in merged:
                    positions[s_key] = entry_id
                    try:
                        ev = json.loads(fields.get("e", "{}"))
                    except ValueError:
                        continue
                    scope = "watch" if s_key.startswith("ev:watch:") else "user"
                    payload = {"scope": scope, "stream": s_key.split(":", 2)[-1], **ev}
                    yield (f"id: {_encode_pos(positions)}\nevent: {ev.get('type', 'message')}\n"
                           f"data: {json.dumps(payload, default=str)}\n\n").encode()
        finally:
            # Starlette cancels this task when the client leaves; shield the cleanup or the await is cancelled too
            # and the slot stays taken until its lease expires.
            with anyio.CancelScope(shield=True):
                await r.zrem(leases, conn_id)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
