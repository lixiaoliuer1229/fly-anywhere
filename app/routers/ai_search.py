from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import FlightOffer as FlightOfferRecord
from app.models import SearchRun
from app.schemas import (
    FlightSearchRequest,
    FlightSearchResult,
    PriceTrendPoint,
    PriceTrendResponse,
    PriceTrendSeries,
)
from app.services.flight_search_agent import search_flight_prices

router = APIRouter(prefix="/api/ai", tags=["ai-search"])


@router.get("/price-trends", response_model=PriceTrendResponse)
def price_trends(
    departure: str | None = None,
    arrival: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """按搜索批次聚合最低网页参考价，供折线图展示。"""
    limit = max(1, min(limit, 500))
    query = (
        db.query(
            FlightOfferRecord.departure,
            FlightOfferRecord.arrival,
            FlightOfferRecord.currency,
            FlightOfferRecord.search_run_id,
            SearchRun.completed_at,
            func.min(FlightOfferRecord.price).label("min_price"),
            func.count(FlightOfferRecord.id).label("offer_count"),
        )
        .join(SearchRun, SearchRun.id == FlightOfferRecord.search_run_id)
        .filter(
            SearchRun.status == "completed",
            SearchRun.completed_at.isnot(None),
            FlightOfferRecord.price.isnot(None),
        )
    )
    if departure:
        query = query.filter(FlightOfferRecord.departure == departure)
    if arrival:
        query = query.filter(FlightOfferRecord.arrival == arrival)

    rows = (
        query.group_by(
            FlightOfferRecord.departure,
            FlightOfferRecord.arrival,
            FlightOfferRecord.currency,
            FlightOfferRecord.search_run_id,
            SearchRun.completed_at,
        )
        .order_by(SearchRun.completed_at.desc())
        .limit(limit)
        .all()
    )

    grouped: dict[tuple[str, str, str], list[PriceTrendPoint]] = {}
    for row in reversed(rows):
        key = (row.departure, row.arrival, row.currency)
        grouped.setdefault(key, []).append(PriceTrendPoint(
            searched_at=row.completed_at,
            min_price=float(row.min_price),
            offer_count=row.offer_count,
            search_run_id=row.search_run_id,
        ))

    series = [
        PriceTrendSeries(departure=key[0], arrival=key[1], currency=key[2], points=points)
        for key, points in grouped.items()
    ]
    total_points = sum(len(item.points) for item in series)
    note = (
        "建议累计至少 8 次同航线查询后判断价格趋势。"
        if total_points < 8
        else "折线展示每次 AI 搜索中可确认报价的最低值。"
    )
    return PriceTrendResponse(series=series, total_points=total_points, note=note)


@router.post("/search", response_model=FlightSearchResult)
async def search_flights(data: FlightSearchRequest, db: Session = Depends(get_db)):
    run = SearchRun(
        original_query=data.query,
        status="running",
        provider="tavily",
        model=settings.ANTHROPIC_MODEL if settings.AI_PROVIDER == "anthropic" else settings.AI_MODEL,
        started_at=datetime.now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        result = await search_flight_prices(data.query)
        run.status = "completed"
        run.summary = result.summary
        run.warning = result.warning
        run.completed_at = datetime.now()
        for offer in result.offers:
            db.add(FlightOfferRecord(
                search_run_id=run.id,
                airline=offer.airline,
                flight_number=offer.flight_number,
                departure=offer.departure,
                arrival=offer.arrival,
                departure_time=offer.departure_time,
                arrival_time=offer.arrival_time,
                price=Decimal(str(offer.price)) if offer.price is not None else None,
                currency=offer.currency.upper(),
                cabin_class=offer.cabin_class,
                source_title=offer.source_title,
                source_url=str(offer.source_url),
                evidence=offer.evidence,
                is_starting_price="起" in offer.evidence,
                created_at=datetime.now(),
            ))
        db.commit()
        return result
    except RuntimeError as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now()
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:4000]
        run.completed_at = datetime.now()
        db.commit()
        raise HTTPException(status_code=502, detail=f"AI 联网搜索失败：{exc}") from exc
