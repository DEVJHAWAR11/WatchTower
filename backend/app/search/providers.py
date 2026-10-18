"""Web search behind one interface: Tavily first, Brave as fallback. Cached and budgeted."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import cache_get_json, cache_set_json, get_redis
from app.fetch.ssrf import SSRFBlocked, validate_url
from app.fetch.urls import canonicalize_url
from app.observability.metrics import SEARCH_CALLS

log = get_logger(__name__)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str


class SearchError(Exception):
    pass


class SearchBudgetExceeded(SearchError):
    pass


class SearchQuotaExhausted(SearchError):
    """The provider says our plan's credits are used up (Tavily 432/433, HTTP 402)."""


_QUOTA_STATUSES = {402, 432, 433}


class SearchProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    async def search(self, query: str, *, max_results: int, country: str | None) -> list[SearchHit]: ...


class TavilyProvider:
    name = "tavily"

    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http

    def available(self) -> bool:
        return bool(get_settings().tavily_api_key.get_secret_value())

    async def search(self, query: str, *, max_results: int, country: str | None) -> list[SearchHit]:
        body: dict[str, object] = {"query": query, "search_depth": "basic", "max_results": max_results,
                                   "include_answer": False, "include_raw_content": False}
        if country == "IN":
            body["country"] = "india"
        headers = {"Authorization": f"Bearer {get_settings().tavily_api_key.get_secret_value()}"}
        async with (self._http or httpx.AsyncClient(timeout=15.0, trust_env=False)) as client:
            resp = await client.post("https://api.tavily.com/search", json=body, headers=headers)
        if resp.status_code in _QUOTA_STATUSES:
            raise SearchQuotaExhausted(f"tavily quota exhausted (http {resp.status_code})")
        if resp.status_code >= 400:
            raise SearchError(f"tavily http {resp.status_code}")
        data = resp.json()
        return [
            SearchHit(title=str(r.get("title", ""))[:200], url=str(r.get("url", "")),
                      snippet=str(r.get("content", ""))[:500], provider=self.name)
            for r in data.get("results", [])
        ]


class BraveProvider:
    name = "brave"

    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http

    def available(self) -> bool:
        return bool(get_settings().brave_api_key.get_secret_value())

    async def search(self, query: str, *, max_results: int, country: str | None) -> list[SearchHit]:
        params: dict[str, str | int] = {"q": query, "count": min(max_results, 20), "safesearch": "strict"}
        if country:
            params["country"] = country
        headers = {"X-Subscription-Token": get_settings().brave_api_key.get_secret_value(),
                   "Accept": "application/json"}
        async with (self._http or httpx.AsyncClient(timeout=15.0, trust_env=False)) as client:
            resp = await client.get("https://api.search.brave.com/res/v1/web/search", params=params, headers=headers)
        if resp.status_code in _QUOTA_STATUSES:
            raise SearchQuotaExhausted(f"brave quota exhausted (http {resp.status_code})")
        if resp.status_code >= 400:
            raise SearchError(f"brave http {resp.status_code}")
        data = resp.json()
        return [
            SearchHit(title=str(r.get("title", ""))[:200], url=str(r.get("url", "")),
                      snippet=str(r.get("description", ""))[:500], provider=self.name)
            for r in (data.get("web") or {}).get("results", [])
        ]


class SearchService:
    def __init__(self, providers: list[SearchProvider] | None = None):
        self.providers = providers if providers is not None else [TavilyProvider(), BraveProvider()]

    async def _take_budget(self) -> None:
        key = f"search:calls:{datetime.now(UTC).strftime('%Y%m%d')}"
        r = get_redis()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 2 * 24 * 3600)
        if n > get_settings().search_daily_budget_calls:
            raise SearchBudgetExceeded("Daily search budget exhausted")

    @staticmethod
    def _month_key(provider: str) -> str:
        return f"search:month:{provider}:{datetime.now(UTC).strftime('%Y%m')}"

    async def _provider_has_credit(self, provider: str) -> bool:
        cap = get_settings().search_monthly_budget.get(provider)
        if cap is None:
            return True
        return int(await get_redis().get(self._month_key(provider)) or 0) < cap

    async def _spend_credit(self, provider: str, *, exhausted: bool = False) -> None:
        r = get_redis()
        key = self._month_key(provider)
        if exhausted:
            cap = get_settings().search_monthly_budget.get(provider, 10**9)
            await r.set(key, cap, ex=32 * 24 * 3600)
            log.warning("search_provider_quota_exhausted", provider=provider)
            return
        if await r.incr(key) == 1:
            await r.expire(key, 32 * 24 * 3600)

    async def credits(self) -> dict[str, dict[str, int | None]]:
        """Monthly usage per provider (admin view)."""
        out: dict[str, dict[str, int | None]] = {}
        for p in self.providers:
            used = int(await get_redis().get(self._month_key(p.name)) or 0)
            out[p.name] = {"used_this_month": used, "monthly_budget": get_settings().search_monthly_budget.get(p.name)}
        return out

    async def search(self, query: str, *, max_results: int = 8, country: str | None = "IN") -> list[SearchHit]:
        q = " ".join(query.split())[:300]
        if not q:
            return []
        key = "search:" + hashlib.sha256(f"{q}|{max_results}|{country}".encode()).hexdigest()
        cached = await cache_get_json(key)
        if cached is not None:
            SEARCH_CALLS.labels(provider="cache", status="hit").inc()
            return [SearchHit(**h) for h in cached]
        usable = [p for p in self.providers if p.available()]
        if not usable:
            raise SearchError("No search provider configured")
        usable = [p for p in usable if await self._provider_has_credit(p.name)]
        if not usable:
            raise SearchBudgetExceeded("Monthly search credits exhausted on every provider")
        await self._take_budget()
        last: Exception | None = None
        for p in usable:
            try:
                await self._spend_credit(p.name)
                hits = await p.search(q, max_results=max_results, country=country)
                SEARCH_CALLS.labels(provider=p.name, status="ok").inc()
                clean = _clean_hits(hits)
                await cache_set_json(key, [h.__dict__ for h in clean], get_settings().search_cache_ttl_seconds)
                return clean
            except SearchQuotaExhausted as e:
                SEARCH_CALLS.labels(provider=p.name, status="quota").inc()
                await self._spend_credit(p.name, exhausted=True)
                last = e
            except (SearchError, httpx.HTTPError, ValueError) as e:
                SEARCH_CALLS.labels(provider=p.name, status="error").inc()
                log.warning("search_provider_failed", provider=p.name, error=str(e))
                last = e
        raise SearchError(f"All search providers failed: {last}")


def _clean_hits(hits: list[SearchHit]) -> list[SearchHit]:
    out: list[SearchHit] = []
    seen: set[str] = set()
    for h in hits:
        try:
            validate_url(h.url)
            canon = canonicalize_url(h.url)
        except (SSRFBlocked, ValueError):
            continue
        if canon in seen:
            continue
        seen.add(canon)
        out.append(SearchHit(title=h.title, url=canon, snippet=h.snippet, provider=h.provider))
    return out


_search: SearchService | None = None


def get_search() -> SearchService:
    global _search
    if _search is None:
        _search = SearchService()
    return _search


def set_search(svc: SearchService | None) -> None:
    global _search
    _search = svc
