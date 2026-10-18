"""Shared Groq rate governor: buckets, priorities, header sync, 429 handling, and deferral of checks."""

import json

import httpx
import pytest
from httpx import Response
from pydantic import BaseModel

from app.core.config import get_settings
from app.llm import ratelimit
from app.llm.client import GroqClient, LLMRateLimited
from app.search.providers import SearchBudgetExceeded, SearchService, TavilyProvider

GROQ = "https://api.groq.com/openai/v1/chat/completions"
SMART, FAST = "openai/gpt-oss-120b", "openai/gpt-oss-20b"


class Out(BaseModel):
    answer: str


def ok(headers: dict[str, str] | None = None, pt: int = 50, ct: int = 10) -> Response:
    return Response(200, headers=headers or {}, json={
        "choices": [{"message": {"content": '{"answer": "ok"}'}}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct}})


@pytest.fixture
def groq():
    return GroqClient(http=httpx.AsyncClient(base_url="https://api.groq.com/openai/v1"))


@pytest.fixture
def tiny_limits(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_rate_limits", {"*": (20, 2000)})
    monkeypatch.setattr(s, "llm_max_wait_background_s", 0.0)
    monkeypatch.setattr(s, "llm_max_wait_interactive_s", 0.0)
    return s


def test_parse_duration() -> None:
    assert ratelimit.parse_duration("1m26.4s") == pytest.approx(86.4)
    assert ratelimit.parse_duration("547ms") == pytest.approx(0.547)
    assert ratelimit.parse_duration("2h1m") == pytest.approx(7260)
    assert ratelimit.parse_duration("7") == 7.0
    assert ratelimit.parse_duration("") is None and ratelimit.parse_duration("soon") is None


async def test_token_bucket_blocks_then_reports_wait(tiny_limits) -> None:  # noqa: ANN001
    assert await ratelimit.try_reserve(SMART, 1500, ratelimit.PRIORITY_INTERACTIVE) == 0
    wait_ms = await ratelimit.try_reserve(SMART, 1500, ratelimit.PRIORITY_INTERACTIVE)
    assert 25_000 < wait_ms <= 60_000  # 1000 tokens short at 2000/min
    await ratelimit.refund(SMART, 1500)  # the call used far less than estimated
    assert await ratelimit.try_reserve(SMART, 1500, ratelimit.PRIORITY_INTERACTIVE) == 0


async def test_interactive_reserve_is_off_limits_to_background(tiny_limits) -> None:  # noqa: ANN001
    # 20 requests/day with a 15% reserve: background may use 17, interactive can still get the last 3
    got = 0
    while await ratelimit.try_reserve(FAST, 1, ratelimit.PRIORITY_BACKGROUND) == 0:
        got += 1
    assert got == 17
    assert await ratelimit.try_reserve(FAST, 1, ratelimit.PRIORITY_INTERACTIVE) == 0


async def test_headers_resync_buckets_and_exhaustion_blocks(groq, respx_mock, tiny_limits) -> None:  # noqa: ANN001
    respx_mock.post(GROQ).mock(return_value=ok({"x-ratelimit-remaining-requests": "0",
                                                "x-ratelimit-reset-requests": "1m26.4s",
                                                "x-ratelimit-remaining-tokens": "100"}))
    r = await groq.structured(purpose="judge", tier="smart", system="s", user="u", schema=Out, cache=False)
    assert r.model == SMART
    st = await ratelimit.status(SMART)
    assert st["tokens_left"] <= 200 and st["blocked_for_s"] and st["blocked_for_s"] > 80


async def test_429_blocks_model_for_all_processes(groq, respx_mock, tiny_limits) -> None:  # noqa: ANN001
    calls: list[str] = []

    def handler(request):  # noqa: ANN001, ANN202
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == SMART:
            return Response(429, headers={"retry-after": "30"}, json={"error": {"message": "rate"}})
        return ok()

    respx_mock.post(GROQ).mock(side_effect=handler)
    r1 = await groq.structured(purpose="judge", tier="smart", system="s", user="a", schema=Out, cache=False)
    r2 = await groq.structured(purpose="judge", tier="smart", system="s", user="b", schema=Out, cache=False)
    assert r1.model == r2.model == FAST
    assert calls == [SMART, FAST, FAST]  # second call never touched the blocked model


async def test_all_models_at_quota_raises_rate_limited(groq, respx_mock, tiny_limits) -> None:  # noqa: ANN001
    route = respx_mock.post(GROQ).mock(return_value=ok())
    await ratelimit.block_for(SMART, 120, "test")
    await ratelimit.block_for(FAST, 45, "test")
    with pytest.raises(LLMRateLimited) as e:
        await groq.structured(purpose="judge", tier="smart", system="s", user="c", schema=Out, cache=False)
    assert 40 <= e.value.retry_after <= 45 and route.call_count == 0


async def test_rate_limited_check_is_deferred_not_failed(monkeypatch) -> None:  # noqa: ANN001
    from app.agents import evaluate

    out = evaluate._llm_error_result({}, "judge", LLMRateLimited("busy", retry_after=40), 0.0)  # type: ignore[arg-type]
    assert out["outcome"] == "deferred" and out["defer"] and out["llm_retry_after"] == 45


async def test_search_monthly_credits_and_quota_response(respx_mock, monkeypatch) -> None:  # noqa: ANN001
    s = get_settings()
    monkeypatch.setattr(s, "search_monthly_budget", {"tavily": 2})
    route = respx_mock.post("https://api.tavily.com/search").mock(return_value=Response(200, json={"results": []}))
    svc = SearchService([TavilyProvider()])
    await svc.search("one")
    await svc.search("two")
    with pytest.raises(SearchBudgetExceeded):
        await svc.search("three")
    assert route.call_count == 2
    assert (await svc.credits())["tavily"] == {"used_this_month": 2, "monthly_budget": 2}

    monkeypatch.setattr(s, "search_monthly_budget", {"tavily": 100})
    route.mock(return_value=Response(432, json={"detail": "plan limit"}))
    with pytest.raises(Exception):  # noqa: B017 - provider failed with quota
        await svc.search("four")
    with pytest.raises(SearchBudgetExceeded):  # marked exhausted for the month: no more calls
        await svc.search("five")
    assert route.call_count == 3


def test_own_private_data_is_rejected_not_refused() -> None:
    from app.agents.intake import normalize_analysis
    from app.agents.schemas import IntakeAnalysis

    own = IntakeAnalysis.model_construct(safety="refuse", safety_category="other", feasibility="not_web_observable")
    assert normalize_analysis(own).safety == "allowed"
    stalking = IntakeAnalysis.model_construct(safety="refuse", safety_category="stalking_private_person",
                                              feasibility="not_web_observable")
    assert normalize_analysis(stalking).safety == "refuse"  # real harm stays refused
