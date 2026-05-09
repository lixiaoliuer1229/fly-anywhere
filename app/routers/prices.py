import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Route
from app.schemas import PriceOut
from app.services.api_source import AviationStackSource
from app.services.price_service import fetch_and_store_prices, get_price_history, get_latest_prices
from app.config import settings

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/latest")
def latest_prices(db: Session = Depends(get_db)):
    rows = get_latest_prices(db)
    result = []
    for price, route in rows:
        result.append({
            "route_id": route.id,
            "departure": route.departure_city,
            "arrival": route.arrival_city,
            "airline": route.airline,
            "price": price.price,
            "cabin_class": price.cabin_class,
            "source": price.source,
            "scraped_at": price.scraped_at.isoformat(),
        })
    return result


@router.get("/{route_id}", response_model=list[PriceOut])
def price_history(route_id: int, limit: int = 100, db: Session = Depends(get_db)):
    return get_price_history(db, route_id, limit)


@router.post("/fetch/{route_id}")
async def manual_fetch(route_id: int, db: Session = Depends(get_db)):
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        return {"error": "Route not found"}

    if not settings.API_KEY:
        return {"error": "API key not configured"}

    source = AviationStackSource(api_key=settings.API_KEY)
    stored = await fetch_and_store_prices(db, route, source)
    return {"fetched": len(stored)}
