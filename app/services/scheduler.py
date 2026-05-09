import threading
import time

import schedule

from app.database import SessionLocal
from app.models import Route
from app.services.api_source import AviationStackSource
from app.services.price_service import fetch_and_store_prices
from app.config import settings


def run_price_fetch():
    """Fetch prices for all routes."""
    db = SessionLocal()
    try:
        routes = db.query(Route).all()
        if not routes:
            print("No routes configured, skipping fetch.")
            return

        source = AviationStackSource(api_key=settings.API_KEY) if settings.API_KEY else None
        if not source:
            print("No API key configured, skipping fetch.")
            return

        import asyncio
        for route in routes:
            try:
                asyncio.run(fetch_and_store_prices(db, route, source))
                print(f"Fetched prices for {route.departure_city} -> {route.arrival_city}")
            except Exception as e:
                print(f"Error fetching {route.departure_city}->{route.arrival_city}: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler."""
    hours = settings.SCRAPE_INTERVAL_HOURS
    schedule.every(hours).hours.do(run_price_fetch)
    print(f"Scheduler started: fetching every {hours} hours")

    def run_loop():
        while True:
            schedule.run_pending()
            time.sleep(60)

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    return thread
