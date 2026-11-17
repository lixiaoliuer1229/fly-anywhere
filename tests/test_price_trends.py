import unittest
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import FlightOffer, Route, SearchRun
from app.routers.ai_search import price_trends


class PriceTrendTests(unittest.TestCase):
    def test_trends_keep_return_date_options_separate(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            for day, prices in ((7, (1100, 1000)), (8, (1300, 1200))):
                route = Route(departure_city='BNE', arrival_city='CNS',
                              departure_date=date(2027, 2, 4), return_date=date(2027, 2, day))
                for minute, price in enumerate(prices):
                    run = SearchRun(route=route, original_query='test', status='completed',
                                    completed_at=datetime(2026, 11, 18, 1, 30 + minute))
                    db.add(FlightOffer(search_run=run, departure='Brisbane', arrival='Cairns',
                                       price=price, source_title='Test', source_url='https://example.com',
                                       evidence='Test quote'))
            db.commit()
            trends = price_trends(departure='BNE', arrival='CNS', db=db)

        self.assertEqual(trends.total_points, 4)
        self.assertEqual(
            {series.return_date: [point.min_price for point in series.points] for series in trends.series},
            {date(2027, 2, 7): [1100, 1000], date(2027, 2, 8): [1300, 1200]},
        )
