import json
import uuid

import httpx
import pytest
from httpx import Response
from pydantic import BaseModel

from app.core.redis import get_redis
from app.llm.client import (
    GroqClient,
    LLMBudgetExceeded,
    LLMOutputInvalid,
    LLMUnavailable,
    record_usage,
    spend_today_usd,
)
from app.search.providers import (
    BraveProvider,
    SearchBudgetExceeded,
    SearchError,
    SearchService,
    TavilyProvider,
)

GROQ = "https://api.groq.com/openai/v1/chat/completions"


class Out(BaseModel):
    answer: str
    score: float


def completion(content: str, pt: int = 100, ct: int = 20) -> Response:
    return Response(200, json={"choices": [{"message": {"content": content}}],
                               "usage": {"prompt_tokens": pt, "completion_tokens": ct}})


@pytest.fixture
def groq():
    return GroqClient(http=httpx.AsyncClient(base_url="https://api.groq.com/openai/v1"))


async def test_structured_output_cost_and_cache(groq, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.post(GROQ).mock(return_value=completion('```json\n{"answer": "yes", "score": 0.9}\n```'))
    r = await groq.structured(purpose="t", tier="smart", system="s", user="u", schema=Out)
    assert r.data.answer == "yes" and r.prompt_tokens == 100 and r.cost_usd > 0 and not r.cached
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "openai/gpt-oss-120b" and body["response_format"]["type"] == "json_schema"
    assert body["reasoning_effort"] == "low"
    r2 = await groq.structured(purpose="t", tier="smart", system="s", user="u", schema=Out)
    assert r2.cached and route.call_count == 1  # identical prompt served from cache
    assert await spend_today_usd() > 0


async def test_invalid_output_is_repaired_once(groq, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.post(GROQ).mock(side_effect=[completion('{"answer": "x"}'), completion('{"answer": "x", "score": 1}')])
    r = await groq.structured(purpose="t", tier="fast", system="s", user="u2", schema=Out)
    assert r.data.score == 1 and route.call_count == 2
    repair_msgs = json.loads(route.calls[1].request.content)["messages"]
    assert "invalid" in repair_msgs[-1]["content"]


async def test_garbage_twice_raises(groq, respx_mock) -> None:  # noqa: ANN001
    respx_mock.post(GROQ).mock(return_value=completion("I am not JSON"))
    with pytest.raises(LLMOutputInvalid):
        await groq.structured(purpose="t", tier="fast", system="s", user="u3", schema=Out)


async def test_rate_limit_falls_down_the_ladder(groq, respx_mock, monkeypatch) -> None:  # noqa: ANN001
    import app.llm.client as mod

    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", no_sleep)
    calls = []

    def handler(request):  # noqa: ANN001, ANN202
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "openai/gpt-oss-120b":
            return Response(429, headers={"retry-after": "1"}, json={"error": {"message": "rate"}})
        return completion('{"answer": "fallback", "score": 0.5}')

    respx_mock.post(GROQ).mock(side_effect=handler)
    r = await groq.structured(purpose="t", tier="smart", system="s", user="u4", schema=Out)
    assert r.data.answer == "fallback" and r.model == "openai/gpt-oss-20b"
    # a 429 blocks the model for everyone and goes straight to the next model (own quota), no hammering
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


async def test_outage_raises_unavailable(groq, respx_mock, monkeypatch) -> None:  # noqa: ANN001
    import app.llm.client as mod

    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", no_sleep)
    respx_mock.post(GROQ).mock(return_value=Response(503))
    with pytest.raises(LLMUnavailable):
        await groq.structured(purpose="t", tier="smart", system="s", user="u5", schema=Out)


async def test_budgets(groq, respx_mock) -> None:  # noqa: ANN001
    respx_mock.post(GROQ).mock(return_value=completion('{"answer": "a", "score": 1}'))
    uid = uuid.uuid4()
    await record_usage("m", "p", 0, 0, 0.0, user_id=uid)
    await get_redis().set(f"llm:user:{uid}:{__import__('datetime').datetime.now(__import__('datetime').UTC):%Y%m%d}", 999_999)
    with pytest.raises(LLMBudgetExceeded) as e:
        await groq.structured(purpose="t", tier="smart", system="s", user="u6", schema=Out, user_id=uid,
                              token_limit_per_day=1000)
    assert e.value.code == "user_budget"
    from app.core.config import get_settings

    soft = get_settings().llm_daily_budget_usd
    await record_usage("m", "p", 0, 0, soft + 0.5)  # just past the soft cap
    with pytest.raises(LLMBudgetExceeded) as e:
        await groq.structured(purpose="t", tier="smart", system="s", user="u7", schema=Out, plan_id="free")
    assert e.value.code == "global_budget_soft"
    r = await groq.structured(purpose="t", tier="smart", system="s", user="u8", schema=Out, plan_id="plus")
    assert r.data.answer == "a"  # paid plans keep working until the hard cap
    await record_usage("m", "p", 0, 0, soft)  # total now beyond the hard cap (2x soft)
    with pytest.raises(LLMBudgetExceeded) as e:
        await groq.structured(purpose="t", tier="smart", system="s", user="u9", schema=Out, plan_id="pro")
    assert e.value.code == "global_budget_hard"


async def test_search_fallback_cache_and_ssrf_filter(respx_mock) -> None:  # noqa: ANN001
    respx_mock.post("https://api.tavily.com/search").mock(return_value=Response(500))
    brave = respx_mock.get("https://api.search.brave.com/res/v1/web/search").mock(return_value=Response(200, json={
        "web": {"results": [
            {"title": "SSC", "url": "https://ssc.gov.in/?utm_source=x", "description": "official"},
            {"title": "evil", "url": "http://169.254.169.254/latest", "description": ""},
            {"title": "dup", "url": "https://ssc.gov.in/", "description": ""}]}}))
    svc = SearchService([TavilyProvider(), BraveProvider()])
    hits = await svc.search("ssc notices")
    assert [h.url for h in hits] == ["https://ssc.gov.in/"] and hits[0].provider == "brave"
    assert brave.calls[0].request.url.params["country"] == "IN"
    again = await svc.search("ssc notices")
    assert len(again) == 1 and brave.call_count == 1


async def test_search_budget_and_no_provider(respx_mock, monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    respx_mock.post("https://api.tavily.com/search").mock(return_value=Response(200, json={"results": []}))
    monkeypatch.setattr(get_settings(), "search_daily_budget_calls", 2)
    svc = SearchService([TavilyProvider()])
    await svc.search("a")
    await svc.search("b")
    with pytest.raises(SearchBudgetExceeded):
        await svc.search("c")

    class Off:
        name = "off"

        def available(self) -> bool:
            return False

    with pytest.raises(SearchError):
        await SearchService([Off()]).search("d")  # type: ignore[list-item]
