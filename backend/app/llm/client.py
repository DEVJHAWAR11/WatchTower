"""Groq LLM client: model ladder, structured output, caching, budgets, retries, cost accounting.

Usage:
    res = await get_llm().structured(purpose="judge", tier="smart", system=..., user=..., schema=Verdict,
                                     user_id=uid, plan_id="free")
    res.data  # validated pydantic instance
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import cache_get_json, cache_set_json, get_redis
from app.observability.metrics import LLM_CALLS, LLM_COST, LLM_LATENCY, LLM_TOKENS

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    code = "llm_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMBudgetExceeded(LLMError):
    code = "llm_budget"


class LLMOutputInvalid(LLMError):
    code = "llm_invalid_output"


@dataclass
class LLMResult[T]:
    data: T
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    latency_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProtocol(Protocol):
    async def structured(
        self, *, purpose: str, tier: str, system: str, user: str, schema: type[T], user_id: uuid.UUID | None = None,
        plan_id: str = "free", max_tokens: int = 1500, temperature: float = 0.1, cache: bool = True,
        token_limit_per_day: int | None = None,
    ) -> LLMResult[T]: ...


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    if not t.startswith(("{", "[")):
        start = t.find("{")
        end = t.rfind("}")
        if start >= 0 and end > start:
            t = t[start : end + 1]
    return t


def _schema_for(schema: type[BaseModel]) -> dict[str, Any]:
    js = schema.model_json_schema()
    js.pop("title", None)
    return js


async def record_usage(model: str, purpose: str, prompt_t: int, completion_t: int, cost: float,
                       *, cache_hit: bool = False, error: bool = False, user_id: uuid.UUID | None = None) -> None:
    r = get_redis()
    day = _today()
    key = f"llmstat:{day}"
    base = f"{model}|{purpose}"
    pipe = r.pipeline(transaction=False)
    pipe.hincrby(key, f"{base}|calls", 0 if cache_hit else 1)
    pipe.hincrby(key, f"{base}|cache_hits", 1 if cache_hit else 0)
    pipe.hincrby(key, f"{base}|prompt_tokens", prompt_t)
    pipe.hincrby(key, f"{base}|completion_tokens", completion_t)
    pipe.hincrby(key, f"{base}|cost_micro", int(cost * 1_000_000))
    pipe.hincrby(key, f"{base}|errors", 1 if error else 0)
    pipe.expire(key, 8 * 24 * 3600)
    if cost:
        pipe.incrby(f"llm:spend:{day}", int(cost * 1_000_000))
        pipe.expire(f"llm:spend:{day}", 3 * 24 * 3600)
    if user_id and (prompt_t or completion_t):
        uk = f"llm:user:{user_id}:{day}"
        pipe.incrby(uk, prompt_t + completion_t)
        pipe.expire(uk, 2 * 24 * 3600)
    await pipe.execute()


async def spend_today_usd() -> float:
    raw = await get_redis().get(f"llm:spend:{_today()}")
    return int(raw or 0) / 1_000_000


async def user_tokens_today(user_id: uuid.UUID) -> int:
    return int(await get_redis().get(f"llm:user:{user_id}:{_today()}") or 0)


class GroqClient:
    def __init__(self, http: httpx.AsyncClient | None = None):
        s = get_settings()
        self.s = s
        self._http = http or httpx.AsyncClient(
            base_url=s.groq_base_url, timeout=httpx.Timeout(s.llm_timeout_seconds, connect=10.0), trust_env=False,
        )
        self._sem = asyncio.Semaphore(s.llm_max_concurrency)

    def _model_for(self, tier: str) -> str:
        return self.s.llm_model_fast if tier == "fast" else self.s.llm_model_smart

    def cost_of(self, model: str, prompt_t: int, completion_t: int) -> float:
        pin, pout = self.s.llm_pricing.get(model, (0.6, 0.8))
        return (prompt_t * pin + completion_t * pout) / 1_000_000

    async def _check_budget(self, plan_id: str, user_id: uuid.UUID | None, token_limit: int | None) -> None:
        spend = await spend_today_usd()
        soft = self.s.llm_daily_budget_usd
        if spend >= soft * self.s.llm_hard_budget_multiplier:
            raise LLMBudgetExceeded("Global LLM budget exhausted for today", code="global_budget_hard")
        if spend >= soft and plan_id == "free":
            raise LLMBudgetExceeded("Free-tier LLM budget exhausted for today", code="global_budget_soft")
        if user_id and token_limit:
            used = await user_tokens_today(user_id)
            if used >= token_limit:
                raise LLMBudgetExceeded("Daily AI usage limit reached for your plan", code="user_budget")

    async def _call(self, model: str, messages: list[dict[str, str]], schema: type[BaseModel], max_tokens: int,
                    temperature: float) -> tuple[str, dict[str, Any]]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if model in self.s.llm_strict_schema_models:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": _schema_for(schema), "strict": False},
            }
        else:
            body["response_format"] = {"type": "json_object"}
        if model in self.s.llm_reasoning_models:
            body["reasoning_effort"] = "low"
        headers = {"Authorization": f"Bearer {self.s.groq_api_key.get_secret_value()}"}
        async with self._sem:
            resp = await self._http.post("/chat/completions", json=body, headers=headers)
        if resp.status_code == 429 or resp.status_code >= 500:
            ra = resp.headers.get("retry-after", "")
            raise LLMUnavailable(f"Groq {resp.status_code}", code=f"http_{resp.status_code}|{ra}")
        if resp.status_code == 400:
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            if err.get("code") == "json_validate_failed":
                failed = err.get("failed_generation") or ""
                return failed, {}
            raise LLMError(f"Groq rejected request: {str(err.get('message', ''))[:200]}", code="bad_request")
        if resp.status_code in (401, 403):
            raise LLMUnavailable("Groq authentication failed", code="auth")
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content") or ""
        return content, data.get("usage") or {}

    async def structured(
        self, *, purpose: str, tier: str, system: str, user: str, schema: type[T], user_id: uuid.UUID | None = None,
        plan_id: str = "free", max_tokens: int = 1500, temperature: float = 0.1, cache: bool = True,
        token_limit_per_day: int | None = None,
    ) -> LLMResult[T]:
        primary = self._model_for(tier)
        schema_json = json.dumps(_schema_for(schema), sort_keys=True)
        cache_key = "llmcache:" + hashlib.sha256(
            f"{tier}\x1f{primary}\x1f{system}\x1f{user}\x1f{schema_json}".encode()
        ).hexdigest()
        if cache:
            hit = await cache_get_json(cache_key)
            if hit is not None:
                try:
                    data = schema.model_validate(hit["data"])
                    LLM_CALLS.labels(model=hit.get("model", primary), purpose=purpose, status="cache").inc()
                    await record_usage(hit.get("model", primary), purpose, 0, 0, 0.0, cache_hit=True)
                    return LLMResult(data=data, model=hit.get("model", primary), cached=True)
                except ValidationError:
                    pass
        await self._check_budget(plan_id, user_id, token_limit_per_day)

        sys_msg = (
            f"{system}\n\nRespond with a single JSON object that conforms to this JSON schema. No prose, no markdown."
            f"\nJSON schema:\n{schema_json}"
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}]
        models = [primary] + [m for m in (self.s.llm_model_fallback,) if m and m != primary]
        last_err: Exception | None = None
        for model in models:
            attempt = 0
            repair_used = False
            msgs = list(messages)
            while attempt < 3:
                attempt += 1
                t0 = time.monotonic()
                try:
                    content, usage = await self._call(model, msgs, schema, max_tokens, temperature)
                except LLMUnavailable as e:
                    last_err = e
                    LLM_CALLS.labels(model=model, purpose=purpose, status="unavailable").inc()
                    await record_usage(model, purpose, 0, 0, 0.0, error=True)
                    if e.code == "auth":
                        raise
                    retry_after = e.code.split("|", 1)[1] if "|" in e.code else ""
                    delay = min(float(retry_after), 20.0) if retry_after.replace(".", "").isdigit() else (
                        0.5 * 2 ** attempt + random.random()
                    )
                    if attempt >= 2:
                        break  # go down the ladder
                    await asyncio.sleep(delay)
                    continue
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = LLMUnavailable(f"Groq transport error: {type(e).__name__}")
                    LLM_CALLS.labels(model=model, purpose=purpose, status="timeout").inc()
                    await record_usage(model, purpose, 0, 0, 0.0, error=True)
                    if attempt >= 2:
                        break
                    await asyncio.sleep(0.5 * 2 ** attempt + random.random())
                    continue
                latency = time.monotonic() - t0
                LLM_LATENCY.labels(model=model).observe(latency)
                pt = int(usage.get("prompt_tokens", 0) or 0)
                ct = int(usage.get("completion_tokens", 0) or 0)
                cost = self.cost_of(model, pt, ct)
                LLM_TOKENS.labels(model=model, kind="prompt").inc(pt)
                LLM_TOKENS.labels(model=model, kind="completion").inc(ct)
                LLM_COST.labels(model=model, purpose=purpose).inc(cost)
                await record_usage(model, purpose, pt, ct, cost, user_id=user_id)
                try:
                    parsed = json.loads(_strip_fences(content))
                    data = schema.model_validate(parsed)
                except (ValueError, ValidationError) as e:
                    LLM_CALLS.labels(model=model, purpose=purpose, status="invalid").inc()
                    last_err = LLMOutputInvalid(f"Invalid structured output: {str(e)[:300]}")
                    if repair_used:
                        break
                    repair_used = True
                    msgs = [
                        *messages,
                        {"role": "assistant", "content": content[:4000]},
                        {"role": "user", "content": (
                            f"That output was invalid: {str(e)[:500]}\nReturn ONLY the corrected JSON object."
                        )},
                    ]
                    continue
                LLM_CALLS.labels(model=model, purpose=purpose, status="ok").inc()
                log.info("llm_call", purpose=purpose, model=model, prompt_tokens=pt, completion_tokens=ct,
                         cost_usd=round(cost, 6), latency_ms=int(latency * 1000))
                if cache:
                    await cache_set_json(cache_key, {"model": model, "data": data.model_dump(mode="json")},
                                         self.s.llm_cache_ttl_seconds)
                return LLMResult(data=data, model=model, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost,
                                 latency_ms=int(latency * 1000))
        if isinstance(last_err, LLMError):
            raise last_err
        raise LLMUnavailable("All models failed")


_llm: LLMProtocol | None = None


def get_llm() -> LLMProtocol:
    global _llm
    if _llm is None:
        _llm = GroqClient()
    return _llm


def set_llm(llm: LLMProtocol | None) -> None:
    """Test/DI hook."""
    global _llm
    _llm = llm
