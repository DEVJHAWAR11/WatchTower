"""Shared Redis client plus small primitives: locks, token bucket, sliding-window limiter, cache."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True, health_check_interval=30)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


# Sliding-window-log limiter, atomic in Lua. Returns {allowed, retry_after_ms}.
_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then retry = (tonumber(oldest[2]) + window) - now end
  return {0, retry}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, 0}
"""

# Token bucket: capacity tokens, refilled at rate tokens/sec. Returns {allowed, wait_ms}.
_BUCKET_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
local elapsed = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * rate)
local allowed = 0
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait = math.ceil(((1 - tokens) / rate) * 1000)
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil((capacity / rate) * 1000) + 1000)
return {allowed, wait}
"""

_RELEASE_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end
"""


async def sliding_window_allow(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    r = get_redis()
    now_ms = int(time.time() * 1000)
    allowed, retry_ms = await r.eval(
        _SLIDING_WINDOW, 1, key, now_ms, window_seconds * 1000, limit, f"{now_ms}-{secrets.token_hex(4)}"
    )
    return bool(int(allowed)), max(1, int(int(retry_ms) / 1000) + 1) if not int(allowed) else 0


async def token_bucket_take(key: str, rate_per_sec: float, capacity: float) -> tuple[bool, int]:
    r = get_redis()
    now_ms = int(time.time() * 1000)
    allowed, wait_ms = await r.eval(_BUCKET_LUA, 1, key, now_ms, rate_per_sec, capacity)
    return bool(int(allowed)), int(wait_ms)


class RedisLock:
    """Simple single-instance Redis lock with owner token (safe release)."""

    def __init__(self, key: str, ttl_ms: int = 30_000):
        self.key = key
        self.ttl_ms = ttl_ms
        self.token = secrets.token_hex(16)
        self.acquired = False

    async def acquire(self) -> bool:
        self.acquired = bool(await get_redis().set(self.key, self.token, nx=True, px=self.ttl_ms))
        return self.acquired

    async def release(self) -> None:
        if self.acquired:
            await get_redis().eval(_RELEASE_LOCK, 1, self.key, self.token)
            self.acquired = False

    async def __aenter__(self) -> RedisLock:
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.release()


async def cache_get_json(key: str) -> Any | None:
    raw = await get_redis().get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
