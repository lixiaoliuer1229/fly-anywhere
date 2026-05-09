from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Route, Price
from app.services.api_source import DataSource, FlightPrice


async def fetch_and_store_prices(db: Session, route: Route, source: DataSource):
    """Fetch prices from a data source and store them in the database."""
    departure = route.departure_city
    arrival = route.arrival_city

    prices = await source.fetch_prices(departure, arrival)

    stored = []
    for fp in prices:
        price_record = Price(
            route_id=route.id,
            price=fp.price,
            cabin_class=fp.cabin_class,
            source=fp.source,
            scraped_at=datetime.now(),
        )
        db.add(price_record)
        stored.append(price_record)

    db.commit()
    return stored


def get_price_history(db: Session, route_id: int, limit: int = 100):
    """Get price history for a route."""
    return (
        db.query(Price)
        .filter(Price.route_id == route_id)
        .order_by(Price.scraped_at.desc())
        .limit(limit)
        .all()
    )


def get_latest_prices(db: Session):
    """Get latest price for each route."""
    from sqlalchemy import func

    subq = (
        db.query(
            Price.route_id,
            func.max(Price.scraped_at).label("latest"),
        )
        .group_by(Price.route_id)
        .subquery()
    )

    return (
        db.query(Price, Route)
        .join(subq, (Price.route_id == subq.c.route_id) & (Price.scraped_at == subq.c.latest))
        .join(Route, Price.route_id == Route.id)
        .all()
    )
