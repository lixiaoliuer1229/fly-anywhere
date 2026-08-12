from datetime import datetime

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch

from app.config import settings
from app.schemas import FlightSearchResult


SYSTEM_PROMPT = """你是一个谨慎的机票价格搜索助手。今天是 {today}。

必须使用 Tavily 搜索公开网页后再回答。搜索时把用户给出的城市、日期、单程/往返、
人数和舱位写进查询；信息不完整时可以搜索已有条件，但必须在 summary 中指出缺失条件。

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


async def search_flight_prices(query: str) -> FlightSearchResult:
    """让 LangChain Agent 联网搜索并返回可直接展示的结构化参考价。"""
    agent = _build_agent()
    state = await agent.ainvoke({"messages": [{"role": "user", "content": query}]})
    result = state.get("structured_response")
    if not isinstance(result, FlightSearchResult):
        result = FlightSearchResult.model_validate(result)

    # 时间由服务端生成，避免模型给出不准确的检索时间。
    return result.model_copy(update={"searched_at": datetime.now()})
