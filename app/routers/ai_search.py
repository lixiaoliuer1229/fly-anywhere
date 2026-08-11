from fastapi import APIRouter, HTTPException

from app.schemas import FlightSearchRequest, FlightSearchResult
from app.services.flight_search_agent import search_flight_prices

router = APIRouter(prefix="/api/ai", tags=["ai-search"])


@router.post("/search", response_model=FlightSearchResult)
async def search_flights(data: FlightSearchRequest):
    try:
        return await search_flight_prices(data.query)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 联网搜索失败：{exc}") from exc
