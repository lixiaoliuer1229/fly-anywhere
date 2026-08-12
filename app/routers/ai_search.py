from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import FlightOffer as FlightOfferRecord
from app.models import SearchRun
from app.schemas import FlightSearchRequest, FlightSearchResult
from app.services.flight_search_agent import search_flight_prices

router = APIRouter(prefix="/api/ai", tags=["ai-search"])


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
