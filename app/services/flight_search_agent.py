import asyncio
from datetime import datetime

import httpx
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch

from app.config import settings
from app.schemas import FlightSearchCriteria, FlightSearchResult
from app.services.structured_flight_sources import (
    AmadeusFlightOffersSource,
    FlightSourceError,
    SerpApiGoogleFlightsSource,
)


SYSTEM_PROMPT = """你是一个谨慎的机票价格搜索助手。今天是 {today}。

必须使用 Tavily 搜索公开网页后再回答。搜索时把用户给出的城市、日期、单程/往返、
人数和舱位写进查询；信息不完整时可以搜索已有条件，但必须在 summary 中指出缺失条件。
只允许执行一轮搜索；这一轮最多并行调用 Tavily 两次。收到搜索结果后不得再次搜索，
必须立即调用 FlightSearchResult 结构化输出工具结束任务。

规则：
1. 只收录搜索结果页面明确支持的价格，绝不猜测或补全价格。
2. source_url 必须是 Tavily 返回的真实页面 URL，evidence 必须简短说明页面呈现了什么。
3. “起价”、促销价或日期不完全匹配的价格必须在 evidence 和 summary 中明确标注。
4. 无法确认价格时返回空 offers，并解释原因。
5. 不得声称价格实时可订，不得声称已经锁定舱位。
6. 尽量返回 3 到 8 个有用结果，重复页面只保留一次。
"""


def _build_agent():
    if not settings.TAVILY_API_KEY:
        raise RuntimeError("未配置 TAVILY_API_KEY")
    if settings.AI_PROVIDER == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("未配置 ANTHROPIC_API_KEY")
        from langchain_anthropic import ChatAnthropic

        model_kwargs = {
            "model": settings.ANTHROPIC_MODEL or settings.AI_MODEL,
            "api_key": settings.ANTHROPIC_API_KEY,
            "temperature": 0,
            "timeout": 60,
        }
        if settings.ANTHROPIC_BASE_URL:
            model_kwargs["base_url"] = settings.ANTHROPIC_BASE_URL
        model = ChatAnthropic(**model_kwargs)
    else:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        model_kwargs = {
            "model": settings.AI_MODEL,
            "api_key": settings.OPENAI_API_KEY,
            "temperature": 0,
            "timeout": 60,
        }
        if settings.OPENAI_BASE_URL:
            model_kwargs["base_url"] = settings.OPENAI_BASE_URL
        # DeepSeek V4 默认启用 thinking。Agent 多轮工具调用若不回传
        # reasoning_content 会失败；机票检索使用非思考模式更快也更稳定。
        if "api.deepseek.com" in (settings.OPENAI_BASE_URL or ""):
            model_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        model = ChatOpenAI(**model_kwargs)
    search = TavilySearch(
        tavily_api_key=settings.TAVILY_API_KEY,
        max_results=8,
        topic="general",
        search_depth="advanced",
        include_answer=False,
        include_raw_content=False,
    )
    return create_agent(
        model=model,
        tools=[search],
        response_format=ToolStrategy(FlightSearchResult),
        system_prompt=SYSTEM_PROMPT.format(today=datetime.now().date().isoformat()),
    )


def _build_model():
    if settings.AI_PROVIDER == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("未配置 ANTHROPIC_API_KEY")
        from langchain_anthropic import ChatAnthropic

        kwargs = {
            "model": settings.ANTHROPIC_MODEL or settings.AI_MODEL,
            "api_key": settings.ANTHROPIC_API_KEY,
            "temperature": 0,
        }
        if settings.ANTHROPIC_BASE_URL:
            kwargs["base_url"] = settings.ANTHROPIC_BASE_URL
        return ChatAnthropic(**kwargs)

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("未配置 OPENAI_API_KEY")
    kwargs = {"model": settings.AI_MODEL, "api_key": settings.OPENAI_API_KEY, "temperature": 0}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    if "api.deepseek.com" in (settings.OPENAI_BASE_URL or ""):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(**kwargs)


async def _parse_criteria(query: str) -> FlightSearchCriteria:
    agent = create_agent(
        model=_build_model(),
        tools=[],
        response_format=ToolStrategy(FlightSearchCriteria),
        system_prompt=(
            f"今天是 {datetime.now().date().isoformat()}。从用户机票需求提取结构化条件。"
            "城市必须转换为最合适的三字 IATA 机场代码；舱位只用 economy、premium_economy、business 或 first。"
            "日期或出发到达信息缺失时不要猜测，应让结构化输出失败。"
        ),
    )
    state = await asyncio.wait_for(
        agent.ainvoke({"messages": [{"role": "user", "content": query}]}),
        timeout=60,
    )
    return FlightSearchCriteria.model_validate(state.get("structured_response"))


async def search_flight_prices(query: str) -> FlightSearchResult:
    """按 SerpApi、Amadeus、Tavily 的顺序查询并自动降级。"""
    failures: list[str] = []
    if settings.SERPAPI_API_KEY or (settings.AMADEUS_API_KEY and settings.AMADEUS_API_SECRET):
        try:
            criteria = await _parse_criteria(query)
        except Exception as exc:
            failures.append(f"结构化行程解析失败：{exc}")
        else:
            sources = []
            if settings.SERPAPI_API_KEY:
                sources.append(SerpApiGoogleFlightsSource())
            if settings.AMADEUS_API_KEY and settings.AMADEUS_API_SECRET:
                sources.append(AmadeusFlightOffersSource())
            for source in sources:
                try:
                    return await source.search(criteria)
                except (FlightSourceError, httpx.HTTPError) as exc:
                    failures.append(f"{source.name}: {exc}")

    return await _search_with_tavily(query, failures)


async def _search_with_tavily(query: str, failures: list[str] | None = None) -> FlightSearchResult:
    """Run only the Tavily fallback; never retry structured providers here."""
    agent = _build_agent()
    state = await asyncio.wait_for(
        agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"recursion_limit": 6},
        ),
        timeout=120,
    )
    result = state.get("structured_response")
    if not isinstance(result, FlightSearchResult):
        result = FlightSearchResult.model_validate(result)

    # 时间由服务端生成，避免模型给出不准确的检索时间。
    warning = result.warning
    if failures:
        warning = f"已自动降级到 Tavily（{'；'.join(failures)}）。{warning}"
    return result.model_copy(update={"searched_at": datetime.now(), "warning": warning, "provider": "tavily"})


async def search_flight_prices_by_criteria(criteria: FlightSearchCriteria) -> FlightSearchResult:
    """Search a known itinerary without spending an LLM call parsing it again."""
    failures: list[str] = []
    sources = []
    if settings.SERPAPI_API_KEY:
        sources.append(SerpApiGoogleFlightsSource())
    if settings.AMADEUS_API_KEY and settings.AMADEUS_API_SECRET:
        sources.append(AmadeusFlightOffersSource())

    for source in sources:
        try:
            return await source.search(criteria)
        except (FlightSourceError, httpx.HTTPError) as exc:
            failures.append(f"{source.name}: {exc}")

    query = (
        f"{criteria.departure_date.isoformat()} 从 {criteria.departure_iata} 到 "
        f"{criteria.arrival_iata}，"
        f"{criteria.return_date.isoformat() + ' 返回，' if criteria.return_date else '单程，'}"
        f"{criteria.adults} 名成人，{criteria.cabin_class}，{criteria.currency}"
    )
    return await _search_with_tavily(query, failures)
