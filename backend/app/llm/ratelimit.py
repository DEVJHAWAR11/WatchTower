"""Shared Groq rate governor: keeps every worker and API process inside the account's per-model limits.

Groq enforces two continuously refilling buckets per model: requests/day (RPD) and tokens/minute (TPM). We mirror
both in Redis (one Lua call reserves from both atomically) and re-sync them from the `x-ratelimit-*` headers of
every response, so the mirror tracks Groq's real numbers even with many processes, restarts, or other users of
the same key. A slice of the request bucket is reserved for interactive work (intake), so a storm of background
checks can never lock users out of creating watches.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger(__name__)

# KEYS: request bucket, token bucket, block key
# ARGV: now_ms, rpd, tpm, tokens wanted, request floor (reserve kept for higher priority)
# Returns {0, 0} on success, {1, wait_ms} when the caller must wait.
_RESERVE_LUA = """
local now = tonumber(ARGV[1])
local rpd = tonumber(ARGV[2])
local tpm = tonumber(ARGV[3])
local want = tonumber(ARGV[4])
local floor = tonumber(ARGV[5])
local block = redis.call('PTTL', KEYS[3])
if block > 0 then return {1, block} end
local function level(key, cap, per_ms)
  local v = redis.call('HMGET', key, 'l', 't')
  local l = tonumber(v[1]) or cap
  local t = tonumber(v[2]) or now
  return math.min(cap, l + math.max(0, now - t) * per_ms)
end
local req_rate = rpd / 86400000
local tok_rate = tpm / 60000
local req = level(KEYS[1], rpd, req_rate)
local tok = level(KEYS[2], tpm, tok_rate)
if want > tpm then want = tpm end
local wait = 0
if req - 1 < floor then wait = math.max(wait, math.ceil((floor + 1 - req) / req_rate)) end
if tok < want then wait = math.max(wait, math.ceil((want - tok) / tok_rate)) end
if wait > 0 then return {1, wait} end
redis.call('HSET', KEYS[1], 'l', req - 1, 't', now)
redis.call('HSET', KEYS[2], 'l', tok - want, 't', now)
redis.call('PEXPIRE', KEYS[1], 172800000)
redis.call('PEXPIRE', KEYS[2], 600000)
return {0, 0}
"""

# Overwrite a bucket with the server's view, but never raise it above what we have reserved locally since.
_SYNC_LUA = """
local now = tonumber(ARGV[1])
local remaining = tonumber(ARGV[2])
local cap = tonumber(ARGV[3])
local per_ms = tonumber(ARGV[4])
local v = redis.call('HMGET', KEYS[1], 'l', 't')
local l = tonumber(v[1]) or cap
local t = tonumber(v[2]) or now
local ours = math.min(cap, l + math.max(0, now - t) * per_ms)
redis.call('HSET', KEYS[1], 'l', math.min(ours, remaining), 't', now)
redis.call('PEXPIRE', KEYS[1], ARGV[5])
return 1
"""

# Return tokens we reserved but did not use (estimate above actual).
_REFUND_LUA = """
local cap = tonumber(ARGV[2])
local l = tonumber(redis.call('HGET', KEYS[1], 'l'))
if l == nil then return 0 end
redis.call('HSET', KEYS[1], 'l', math.min(cap, l + tonumber(ARGV[1])))
return 1
"""

PRIORITY_INTERACTIVE = "interactive"
PRIORITY_BACKGROUND = "background"


@dataclass(frozen=True)
class ModelLimits:
    rpd: int
    tpm: int


def limits_for(model: str) -> ModelLimits:
    s = get_settings()
    rpd, tpm = s.llm_rate_limits.get(model, s.llm_rate_limits.get("*", (1000, 8000)))
    return ModelLimits(int(rpd), int(tpm))


def estimate_tokens(text_chars: int, max_tokens: int) -> int:
    """Groq counts the prompt plus the requested completion budget against TPM at admission time."""
    return int(text_chars / 3.2) + 32 + max_tokens


def _keys(model: str) -> tuple[str, str, str]:
    return f"llm:rl:{model}:req", f"llm:rl:{model}:tok", f"llm:rl:{model}:block"


async def try_reserve(model: str, tokens: int, priority: str) -> int:
    """Reserve one request and `tokens` tokens. Returns 0 when reserved, otherwise milliseconds to wait."""
    lim = limits_for(model)
    reserve = get_settings().llm_interactive_reserve_fraction
    floor = 0 if priority == PRIORITY_INTERACTIVE else int(lim.rpd * reserve)
    rk, tk, bk = _keys(model)
    blocked, wait_ms = await get_redis().eval(
        _RESERVE_LUA, 3, rk, tk, bk, int(time.time() * 1000), lim.rpd, lim.tpm, tokens, floor)
    return int(wait_ms) if int(blocked) else 0


async def acquire(model: str, tokens: int, priority: str, max_wait_s: float) -> float:
    """Wait (up to max_wait_s) for capacity. Returns 0 when acquired, else the seconds until capacity frees up."""
    deadline = time.monotonic() + max_wait_s
    while True:
        wait_ms = await try_reserve(model, tokens, priority)
        if wait_ms <= 0:
            return 0.0
        wait_s = wait_ms / 1000
        left = deadline - time.monotonic()
        if wait_s > left:
            return wait_s
        await asyncio.sleep(wait_s + 0.05)


async def refund(model: str, tokens: int) -> None:
    if tokens > 0:
        await get_redis().eval(_REFUND_LUA, 1, _keys(model)[1], tokens, limits_for(model).tpm)


_DUR = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def parse_duration(raw: str | None) -> float | None:
    """Groq reset headers look like '1m26.4s', '547ms', '7.66s', '2h1m'."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        pass
    m = _DUR.match(raw)
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


async def sync_from_headers(model: str, headers: Mapping[str, str]) -> None:
    """Pull Groq's real remaining counts into our buckets (best effort)."""
    lim = limits_for(model)
    rk, tk, bk = _keys(model)
    now = int(time.time() * 1000)
    r = get_redis()
    try:
        rem_req = headers.get("x-ratelimit-remaining-requests")
        rem_tok = headers.get("x-ratelimit-remaining-tokens")
        if rem_req is not None:
            await r.eval(_SYNC_LUA, 1, rk, now, int(rem_req), lim.rpd, lim.rpd / 86_400_000, 172_800_000)
            if int(rem_req) <= 0:
                reset = parse_duration(headers.get("x-ratelimit-reset-requests")) or 90
                await r.set(bk, "rpd", px=int(reset * 1000))
        if rem_tok is not None:
            await r.eval(_SYNC_LUA, 1, tk, now, int(rem_tok), lim.tpm, lim.tpm / 60_000, 600_000)
    except (ValueError, TypeError) as e:
        log.debug("ratelimit_header_parse_failed", model=model, error=str(e))


async def block_for(model: str, seconds: float, reason: str) -> None:
    """After a 429: stop every process from calling this model until Groq says it's fine again."""
    seconds = max(1.0, min(seconds, 6 * 3600))
    await get_redis().set(_keys(model)[2], reason, px=int(seconds * 1000))
    log.warning("llm_model_blocked", model=model, seconds=round(seconds, 1), reason=reason)


async def status(model: str) -> dict[str, float | int | None]:
    """Current view of a model's buckets (admin/health)."""
    lim = limits_for(model)
    rk, tk, bk = _keys(model)
    r = get_redis()
    now = time.time() * 1000
    out: dict[str, float | int | None] = {"rpd_limit": lim.rpd, "tpm_limit": lim.tpm}
    for name, key, cap, per_ms in (("requests_left", rk, lim.rpd, lim.rpd / 86_400_000),
                                   ("tokens_left", tk, lim.tpm, lim.tpm / 60_000)):
        lv, ts = await r.hmget(key, "l", "t")
        lvl = float(lv) if lv is not None else cap
        t = float(ts) if ts is not None else now
        out[name] = int(min(cap, lvl + max(0.0, now - t) * per_ms))
    pttl = await r.pttl(bk)
    out["blocked_for_s"] = round(pttl / 1000, 1) if pttl and pttl > 0 else None
    return out
