import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal


from app.database import SessionLocal
from app.models import FlightOffer as FlightOfferRecord, Route, SearchRun
from app.schemas import FlightSearchCriteria
from app.services.flight_search_agent import search_flight_prices_by_criteria
from app.config import settings


def run_price_fetch():
    """Fetch and persist prices for enabled, fully specified monitored routes."""
    db = SessionLocal()
    try:
        routes = db.query(Route).filter(Route.enabled.is_(True)).all()
        if not routes:
            print("No routes configured, skipping fetch.")
            return

        import asyncio
        for route in routes:
            if not route.departure_date or not route.return_date:
                print(f"Skipping route {route.id}: departure/return dates are required")
                continue
            query = (
                f"{route.departure_city}->{route.arrival_city} "
                f"{route.departure_date.isoformat()}~{route.return_date.isoformat()}"
            )
            run = SearchRun(
                route_id=route.id,
                original_query=query,
                status="running",
                provider="scheduled",
                model=settings.AI_MODEL,
                started_at=datetime.now(),
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id
            try:
                criteria = FlightSearchCriteria(
                    departure_iata=route.departure_city,
                    arrival_iata=route.arrival_city,
                    departure_date=route.departure_date,
                    return_date=route.return_date,
                    adults=route.adults,
                    cabin_class=route.cabin_class,
                    currency=route.currency,
                )
                result = asyncio.run(search_flight_prices_by_criteria(criteria))
                run.status = "completed"
                run.provider = result.provider
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
                print(f"Fetched {len(result.offers)} offers for {query} via {result.provider}")
            except Exception as e:
                db.rollback()
                run = db.get(SearchRun, run_id)
                run.status = "failed"
                run.error_message = str(e)[:4000]
                run.completed_at = datetime.now()
                db.commit()
                print(f"Error fetching {query}: {e}")
        # Delivery failures must not undo stored prices or stop the scheduler.
        try:
            from app.services.email_report import send_price_report
            send_price_report(db, routes)
        except Exception as exc:
            print(f"Email report failed ({type(exc).__name__}); check SMTP configuration/connectivity.")
    finally:
        db.close()


def next_fetch_at(now):
    """Return the next configured wall-clock time in the configured timezone."""
    local_now = now.astimezone(ZoneInfo(settings.SCRAPE_TIMEZONE))
    clock = datetime.strptime(settings.SCRAPE_DAILY_TIME, "%H:%M").time()
    target = local_now.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target


def start_scheduler():
    """Run once daily at a timezone-aware wall-clock time, then send the report."""
    zone = ZoneInfo(settings.SCRAPE_TIMEZONE)
    next_run = next_fetch_at(datetime.now(zone))
    print(f"Scheduler started: daily {settings.SCRAPE_DAILY_TIME} {settings.SCRAPE_TIMEZONE}; next={next_run.isoformat()}")

    def run_loop():
        nonlocal next_run
        while True:
            remaining = (next_run - datetime.now(zone)).total_seconds()
            if remaining > 0:
                time.sleep(min(30, remaining))
                continue
            try:
                run_price_fetch()
            except Exception as exc:
                print(f"Scheduled fetch failed ({type(exc).__name__}); next daily run remains enabled.")
            finally:
                next_run = next_fetch_at(datetime.now(zone))
                print(f"Next scheduled fetch: {next_run.isoformat()}")

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    return thread
