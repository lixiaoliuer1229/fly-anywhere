import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from app.services.scheduler import next_fetch_at
from app.config import settings

class DailyScheduleTests(unittest.TestCase):
    def test_daily_time_uses_shanghai_independent_of_host_timezone(self):
        with patch.object(settings, 'SCRAPE_DAILY_TIME', '09:30'), patch.object(settings, 'SCRAPE_TIMEZONE', 'Asia/Shanghai'):
            before = datetime(2026, 9, 10, 1, 29, tzinfo=timezone.utc)
            after = datetime(2026, 9, 10, 1, 31, tzinfo=timezone.utc)
            self.assertEqual(next_fetch_at(before).isoformat(), '2026-09-10T09:30:00+08:00')
            self.assertEqual(next_fetch_at(after).isoformat(), '2026-09-11T09:30:00+08:00')

    def test_no_routes_still_sends_one_combined_report(self):
        from unittest.mock import MagicMock
        from app.services.scheduler import run_price_fetch
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        with patch('app.services.scheduler.SessionLocal', return_value=db), \
             patch('app.services.email_report.send_price_report') as send:
            run_price_fetch(exchange_status=False)
        send.assert_called_once_with(db, [], exchange_status=False)
        db.close.assert_called_once()

    def test_excluded_routes_are_not_searched_or_sent(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from app.services.scheduler import run_price_fetch
        db = MagicMock()
        dates = dict(departure_date=date(2027, 2, 4), return_date=date(2027, 2, 11))
        canada = SimpleNamespace(departure_city='CTU', arrival_city='YVR', **dates)
        london = SimpleNamespace(departure_city='CTU', arrival_city=' lhr ', **dates)
        oslo_tianfu = SimpleNamespace(departure_city='TFU', arrival_city='OSL', **dates)
        oslo_shuangliu = SimpleNamespace(departure_city=' ctu ', arrival_city='osl', **dates)
        db.query.return_value.filter.return_value.all.return_value = [canada, london, oslo_tianfu, oslo_shuangliu]
        with patch('app.services.scheduler.SessionLocal', return_value=db), \
             patch('app.services.scheduler.search_flight_prices_by_criteria') as search, \
             patch('app.services.email_report.send_scheduled_reports') as send:
            run_price_fetch()
        search.assert_not_called()
        send.assert_called_once_with(db, [], exchange_status=None)

    def test_canadian_airport_and_city_codes(self):
        from types import SimpleNamespace
        from app.services.route_policy import is_canadian_route
        for code in ('YVR', 'ylw', ' YTO ', 'YMQ', 'YEA'):
            with self.subTest(code=code):
                self.assertTrue(is_canadian_route(SimpleNamespace(departure_city='CTU', arrival_city=code)))
                self.assertTrue(is_canadian_route(SimpleNamespace(departure_city=code, arrival_city='CTU')))
        self.assertFalse(is_canadian_route(SimpleNamespace(departure_city='CTU', arrival_city='JFK')))
