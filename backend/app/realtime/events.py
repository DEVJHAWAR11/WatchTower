"""Realtime events on Redis Streams.

Streams:
  ev:user:{user_id}   - things addressed to one user (alerts, intake progress, deliveries, approvals)
  ev:watch:{watch_id} - live run progress of a watch (shared by every subscriber; no per-subscriber fan-out)

Streams give us replay for free: SSE clients reconnect with Last-Event-ID and XREAD continues from there.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger(__name__)
STREAM_MAXLEN = 500
STREAM_TTL_SECONDS = 3 * 24 * 3600


def user_stream(user_id: uuid.UUID | str) -> str:
    return f"ev:user:{user_id}"


def watch_stream(watch_id: uuid.UUID | str) -> str:
    return f"ev:watch:{watch_id}"


# Atomically take a global sequence number and append, so events from different streams can be merged in true order.
_PUBLISH_LUA = """
local seq = redis.call('INCR', 'ev:seq')
local id = redis.call('XADD', KEYS[1], 'MAXLEN', '~', ARGV[2], '*', 'e', ARGV[1], 's', seq)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return id
"""


async def _publish(stream: str, event_type: str, data: dict[str, Any]) -> str | None:
    payload = json.dumps(
        {"type": event_type, "at": datetime.now(UTC).isoformat(), "data": data}, default=str, separators=(",", ":")
    )
    try:
        return str(await get_redis().eval(_PUBLISH_LUA, 1, stream, payload, STREAM_MAXLEN, STREAM_TTL_SECONDS))
    except Exception as e:  # realtime is best-effort; never break the pipeline because of it
        log.warning("event_publish_failed", stream=stream, type=event_type, error=str(e))
        return None


async def publish_user(user_id: uuid.UUID | str, event_type: str, data: dict[str, Any]) -> str | None:
    return await _publish(user_stream(user_id), event_type, data)


async def publish_watch(watch_id: uuid.UUID | str, event_type: str, data: dict[str, Any]) -> str | None:
    return await _publish(watch_stream(watch_id), event_type, data)
