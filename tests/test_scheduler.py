import unittest
from datetime import datetime, timezone
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
